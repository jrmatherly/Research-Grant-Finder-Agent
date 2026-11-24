from __future__ import annotations
import hashlib, sqlite3
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal
from . import __version__, prompts
from .announcement import GRANTS_FAILED, Announcement, Requirement, fetch_announcement, letters, parse_requirements, quoted_in
from .checks import check_section, identifiers, not_in_crossref
from .clients import ApiError, ReferenceClient
from .llm import ModelError
from .models import Application, Attribution, Completion, Fact, Finding, Model, ModelCall, Opportunity, Review, Revision, Signoff
from .profile import BUILTIN_PROFILE, Profile, ProfileError
from .provenance import PROPOSALS, attribution, disclosure_statement, head, percent, section_state, share
from .rules import FACT_KINDS, GRANT_TYPES, GrantType, Limit, ReviewFactor, SectionRule, describe, grant_types_for
from .store import OpportunityStore

DECISIONS = {None: "not yet decided", True: "confirmed", False: "rejected"}
ORIGINS = {"nih-guide": "the NIH Guide", "grants.gov": "Grants.gov"}
STALE_PROPOSAL = "The section changed after the model read it, so this proposal no longer fits. Ask the model again."
NO_SECTION_IV = "Grant Matcher found no Section IV in this text and read no requirement from it. The standing rules apply."
DROPPED = "It drops an item whose quote is not in the announcement or holds fewer than 20 letters and digits, a limit whose number does not stand on its own in its quote and in the announcement or that names no section, and an item that is not in the form asked for."
ESTIMATE = "the model's estimate, not NIH's"
REVIEW_DROPPED = "It drops a point whose quote is not in the section or holds fewer than 20 letters and digits, and a point that is not in the form asked for."

class WorkspaceError(ValueError):
    pass

class NotReady(Exception):
    def __init__(self, reason: str, findings: tuple[Finding, ...] = ()) -> None:
        super().__init__(reason)
        self.reason, self.findings = reason, findings

class StaleEdit(Exception):
    def __init__(self, head: Revision) -> None:
        super().__init__(f"The {head.section} section changed after you opened it, and revision {head.id} is the newest. Read it before you save or sign.")
        self.head = head

@dataclass(frozen=True)
class Proposal:
    call_id: int
    section: str
    action: str
    parent_id: int | None
    text: str
    findings: tuple[Finding, ...]

@dataclass(frozen=True)
class SectionView:
    rule: SectionRule
    limit: Limit
    text: str
    revision_id: int | None
    state: str
    gaps: tuple[str, ...]
    findings: tuple[Finding, ...]
    attribution: Attribution
    review: Review | None

@dataclass(frozen=True)
class ApplicationView:
    application: Application
    grant_type: GrantType
    announcement: Announcement | None
    requirements: tuple[Requirement, ...]
    facts: tuple[Fact, ...]
    sections: tuple[SectionView, ...]
    log: tuple[Revision, ...]
    notices: tuple[str, ...]
    disclosure: str
    @property
    def no_section_iv(self) -> bool:
        # The notice says that no requirement was read, so a model's reading of Section I or V ends it.
        return self.announcement is not None and not self.announcement.section("IV") and not self.requirements
    def section(self, key: str) -> SectionView:
        for s in self.sections:
            if s.rule.key == key:
                return s
        raise WorkspaceError(f"This application has no section {key}. Its sections are {', '.join(s.rule.key for s in self.sections)}.")

def score_line(factor: ReviewFactor, score: int | str | None) -> str:
    # A review saved before a factor joined its grant type has no score for it.
    if score is None:
        return f"{factor.title}. This review has no score for it."
    return f"{factor.title}, {ESTIMATE}. " + (f"{score} on NIH's scale from 1, exceptional, to 9, poor." if factor.scale == "1-9" else "Appropriate." if score == "appropriate" else f"The model wrote: {score}")

def lookup_line(reference: Fact) -> str:
    if not any(identifiers(reference)):
        return "It has no PMID or DOI, so Grant Matcher cannot check that it exists."
    if (found := reference.detail.get("lookup")) is None:
        return "Not checked yet."
    return f"Checked on {found['on']}. " + (f"{found['service']} holds {found['id']} as: {found['title']}" if found["title"] else not_in_crossref(found["id"]) if found["service"] == "Crossref" else f"{found['service']} has no record of {found['id']}.")

def dropped_points(review: Review) -> str:
    return f"Grant Matcher dropped {review.dropped} point{'' if review.dropped == 1 else 's'} of the reply. {REVIEW_DROPPED}"

def _profile(store: OpportunityStore) -> Profile:
    # The dashboard already says that the saved profile cannot be read, and an application can still be started and checked without it.
    try:
        return store.profile()
    except ProfileError:
        return BUILTIN_PROFILE

def _same(r: Requirement) -> tuple[str, str, str]:
    return r.kind, r.section, r.text

def _quoted(r: Requirement) -> tuple[str, str, str]:
    # A model words the same sentence differently on each reading, so its items are told apart by the sentence they quote.
    return r.kind, r.section, letters(r.quote)

def _reparse(store: OpportunityStore, app_id: int, announcement: Announcement) -> list[tuple[Requirement, str]]:
    rows = store.requirements(app_id)
    decided = [r for r in rows if r.origin == "parsed" and r.confirmed is not None]
    # A decision moves to the newly parsed requirement that says the same thing, while the sentence it was made on is still in the text.
    carried = {_same(r): r.confirmed for r in decided if quoted_in(r.quote, announcement.text)}
    parsed = {_same(r): r for r in parse_requirements(announcement)}
    store.replace_requirements(app_id, "parsed", [replace(r, confirmed=carried.get(key)) for key, r in parsed.items()])
    # A model's item rests on its quote alone, so it stays while the quote is in the new text.
    if gone := [r for r in rows if r.origin == "model" and not quoted_in(r.quote, announcement.text)]:
        store.replace_requirements(app_id, "model", [r for r in rows if r.origin == "model" and r not in gone])
    return [(r, "the new text no longer has the sentence it came from") for r in gone if r.confirmed is not None] + [(r, "Grant Matcher no longer reads that requirement from the new text" if _same(r) in carried else "the new text no longer has the sentence it came from") for r in decided if _same(r) not in carried or _same(r) not in parsed]

def read_summary(found: tuple[Requirement, ...]) -> str:
    # A decided row is carried over from an earlier read, and every other row is from this read, new or read again.
    new, kept = sum(r.confirmed is None for r in found), sum(r.confirmed is not None for r in found)
    return f"The model read {new} requirement{'' if new == 1 else 's'} from the announcement that you have not decided." + (f" Your decision on {kept} requirement{'' if kept == 1 else 's'} read earlier still stands." if kept else "")

def _rules(app: Application) -> tuple[SectionRule, ...]:
    return tuple(s for s in GRANT_TYPES[app.grant_type].sections if app.resubmission or not s.resubmission_only)

def _grounding(facts: tuple[Fact, ...], profile: Profile, revisions: list[Revision], announcement: Announcement | None) -> str:
    # An applicant's revision made after a model's in the same section holds the model's words, so it grounds nothing.
    mine = [r.text for r in revisions if r.author == "applicant" and not any(m.author == "model" and m.section == r.section and m.id < r.id for m in revisions)]
    return "\n".join([*(f.text for f in facts), profile.research_summary, profile.expertise, profile.resources, *mine, announcement.text if announcement else ""])

def _confirmed(rule: SectionRule, requirements: tuple[Requirement, ...]) -> list[Limit]:
    # A limit in pages cannot replace a limit in lines or sentences.
    return [r.limit for r in requirements if r.kind == "limit" and r.confirmed and r.section == rule.key and r.limit and r.limit.unit == rule.limit.unit]

def _limit(rule: SectionRule, requirements: tuple[Requirement, ...]) -> Limit:
    return min(_confirmed(rule, requirements), key=lambda l: l.amount, default=rule.limit)

class Workspace:
    def __init__(self, store: OpportunityStore, application_id: int, model: Model | None = None) -> None:
        app = store.application(application_id)
        if app is None:
            raise WorkspaceError(f"{store.db_path} has no application {application_id}.")
        self.store, self.application_id, self.model = store, application_id, model
        # A close date is never before date.min, so a notice that has closed is found too, with its Grants.gov id.
        self.opportunity = next((s.opportunity for s in store.top_scored(limit=-1, today=date.min) if s.opportunity.opportunity_number == app.opportunity_number), None)

    @classmethod
    def start(cls, store: OpportunityStore, opportunity: Opportunity, grant_type: str, resubmission: bool = False, model: Model | None = None) -> Workspace:
        covered = [f"{g.funder}:{g.code}" for g in grant_types_for(opportunity)]
        if grant_type not in covered:
            raise WorkspaceError(f"Grant Matcher does not write {opportunity.opportunity_number} as {grant_type}." + (f" It can write it as {', '.join(covered)}." if covered else ""))
        prior, before = _profile(store).prior_work, {a.id for a in store.applications()}
        app = store.add_application(opportunity_number=opportunity.opportunity_number, grant_type=grant_type, title=opportunity.title, resubmission=resubmission)
        if app.id not in before:
            for ref in prior:
                store.add_fact(app.id, "reference", ref.citation, ref.key, {k: v for k, v in (("pmid", ref.pmid), ("doi", ref.doi)) if v})
            if (announcement := store.announcement(app.opportunity_number)) is not None:
                store.replace_requirements(app.id, "parsed", parse_requirements(announcement))
        return cls(store, app.id, model)

    def _application(self) -> Application:
        app = self.store.application(self.application_id)
        if app is None:
            raise WorkspaceError(f"{self.store.db_path} has no application {self.application_id}.")
        return app

    def _rule(self, key: str) -> SectionRule:
        rules = _rules(self._application())
        if (rule := next((r for r in rules if r.key == key), None)) is None:
            raise WorkspaceError(f"This application has no section {key}. Its sections are {', '.join(r.key for r in rules)}.")
        return rule

    def view(self) -> ApplicationView:
        app, store = self._application(), self.store
        grant_type, announcement = GRANT_TYPES[app.grant_type], store.announcement(app.opportunity_number)
        requirements, facts = tuple(store.requirements(app.id)), tuple(f for f in store.facts(app.id) if f.retired_at is None)
        revisions, signoffs, profile, reviews = store.revisions(app.id), store.signoffs(app.id), _profile(store), store.reviews(app.id)
        grounding = _grounding(facts, profile, revisions, announcement)
        notices, kinds, sections = [], {f.kind for f in facts}, []
        for rule in _rules(app):
            confirmed, limit = _confirmed(rule, requirements), _limit(rule, requirements)
            if len(confirmed) > 1:
                notices.append(f"You confirmed {len(confirmed)} limits for the {rule.title}. The smallest, {describe(limit)}, applies.")
            notices += [f"You confirmed a limit of {describe(r.limit)} for the {rule.title}. Its own limit is in {rule.limit.unit}, so Grant Matcher does not apply the one you confirmed." for r in requirements if r.kind == "limit" and r.confirmed and r.section == rule.key and r.limit and r.limit.unit != rule.limit.unit]
            current = head(revisions, rule.key)
            words = attribution(revisions, current.id) if current else ()
            text = current.text if current else ""
            findings = check_section(text, rule, limit, grant_type.page, facts, grounding, words) if current else ()
            state = section_state(revisions, signoffs, rule.key)
            if state == "final" and any(f.severity == "error" for f in findings):
                state = "draft"
                notices.append(f"The {rule.title} is a draft again, because an error has appeared since you signed off revision {current.id}. The sign-off stays in the log.")
            # A review is of one revision, so an older one stays in the log and is not shown as current.
            review = next((r for r in reversed(reviews) if current and r.revision_id == current.id), None)
            sections.append(SectionView(rule, limit, text, current.id if current else None, state, tuple(k for k in rule.needs if k not in kinds), findings, share(words), review))
        year = datetime.now(timezone.utc).year
        if app.created_at.year == year and (n := sum(a.created_at.year == year and a.id <= app.id for a in store.applications())) >= 6:
            notices.append(f"This is application {n} that Grant Matcher has started in {year}. NIH accepts six per investigator per calendar year (NOT-OD-25-132). Grant Matcher counts only its own.")
        calls = store.calls(app.id)
        disclosure = disclosure_statement(app, grant_type, revisions, calls, signoffs, facts, {c.id for c in self._waiting(calls, revisions)}, {s.rule.key: s.attribution for s in sections}) if app.disclosure_on else ""
        return ApplicationView(app, grant_type, announcement, requirements, facts, tuple(sections), tuple(revisions), tuple(notices), disclosure)

    def fetch_announcement(self, guide: Any = None, grants: Any = None) -> tuple[Announcement, list[str]]:
        app = self._application()
        # Without a saved record the fetch goes by the number saved with the application.
        opportunity = self.opportunity or Opportunity("", app.opportunity_number, app.title, "", "", "")
        announcement = fetch_announcement(opportunity, guide, grants)
        # Grants.gov is the official source, and the Guide can serve an older text when Grants.gov does not answer.
        if (saved := self.store.announcement(app.opportunity_number)) is not None and saved.origin == "grants.gov" and announcement.origin == "nih-guide":
            raise ApiError(f"{announcement.grants_says} Grant Matcher kept the copy it saved from Grants.gov on {saved.fetched_at:%Y-%m-%d}, because the NIH Guide's text can be older.")
        self.store.save_announcement(announcement)
        # The announcement is saved once for its number, so every application for that number reads it again.
        notes = [f"{announcement.grants_says} So this text is from the NIH Guide and may not be the official one. Fetch again later."] if announcement.grants_says.startswith(GRANTS_FAILED) else []
        dropped = {other.id: _reparse(self.store, other.id, announcement) for other in self.store.applications() if other.opportunity_number == app.opportunity_number}
        # This application's own losses come first.
        for app_id in sorted(dropped, key=lambda app_id: app_id != app.id):
            notes += [("Your decision on" if app_id == app.id else f"Application {app_id} lost its decision on") + f' "{r.text}"' + (" was dropped" if app_id == app.id else "") + f", because {why}." for r, why in dropped[app_id]]
        return announcement, notes

    def extract_requirements(self) -> tuple[tuple[Requirement, ...], int]:
        app = self._application()
        if (announcement := self.store.announcement(app.opportunity_number)) is None:
            raise NotReady("Fetch the full announcement first. The model reads its requirements from the saved text.")
        if not (parts := [(n, text) for n in ("I", "IV", "V") if (text := announcement.section(n))]):
            raise NotReady("Grant Matcher found none of Sections I, IV and V in the announcement, so there is nothing to send.")
        found, dropped = [], 0
        for numeral, text in parts:
            call, done = self._ask("", "extract", prompts.extract(text, numeral, GRANT_TYPES[app.grant_type]), None)
            # A save would delete the undecided rows of the last read, so a reply with no list fails the read as a failed call does.
            if prompts.reply_items(done.text) is None:
                raise ModelError(f"The reply for Section {numeral} was not a list of requirements, so nothing was read. Nothing was changed, and the calls are in the log. Ask again.")
            kept, lost = prompts.parse_requirements(done.text, announcement.text)
            found, dropped = found + [replace(r, call_id=call.id) for r in kept], dropped + lost
        # A decision stays with its item while the item's quote is in the text, and a new reading of the same item does not add it twice.
        items = {_quoted(r): r for r in self.store.requirements(app.id) if r.origin == "model" and r.confirmed is not None and quoted_in(r.quote, announcement.text)}
        for r in found:
            items.setdefault(_quoted(r), r)
        # The announcement has reached the host by now, so a bare database error would hide that it was sent.
        try:
            return tuple(self.store.replace_requirements(app.id, "model", items.values())), dropped
        except sqlite3.Error as exc:
            raise ModelError(f"The announcement text was sent to {self.model.host} and the calls are in the log, but Grant Matcher could not save what the model read ({exc}). Nothing was saved, and asking again sends the text again.") from None

    def decide(self, requirement_id: int, confirmed: bool) -> None:
        if requirement_id not in {r.id for r in self.store.requirements(self.application_id)}:
            raise WorkspaceError(f"Application {self.application_id} has no requirement {requirement_id}.")
        self.store.decide_requirement(requirement_id, confirmed)

    def add_fact(self, kind: str, text: str, label: str = "", detail: dict | None = None) -> Fact:
        if kind not in FACT_KINDS:
            raise WorkspaceError(f"{kind} is not a kind of input. Use one of {', '.join(FACT_KINDS)}.")
        if not text.strip():
            raise WorkspaceError("An input needs text.")
        self._application()
        return self.store.add_fact(self.application_id, kind, text.strip(), label.strip(), detail)

    def retire_fact(self, fact_id: int) -> None:
        if fact_id not in {f.id for f in self.store.facts(self.application_id)}:
            raise WorkspaceError(f"Application {self.application_id} has no input {fact_id}.")
        self.store.retire_fact(fact_id)

    def verify_references(self, client: ReferenceClient | None = None) -> int:
        client, checked, failed, streak = client or ReferenceClient(), 0, [], 0
        references = [f for f in self.store.facts(self.application_id) if f.kind == "reference" and f.retired_at is None and any(identifiers(f))]
        for n, f in enumerate(references):
            pmid, doi = identifiers(f)
            try:
                title = client.lookup(pmid, doi)
            except ApiError as exc:
                # Nothing is recorded for this reference, so "no record" in detail always means that the index said so.
                failed.append(f"{f'[@{f.label}]' if f.label else f.text[:40]}: {str(exc).rstrip('.')}.")
                # Two in a row most likely mean the index is not answering, and each further try can wait half a minute.
                if (streak := streak + 1) == 2:
                    break
                continue
            streak, sent = 0, f"PMID {pmid} to PubMed" if pmid else f"DOI {doi} to Crossref"
            # The applicant typed the text, so the index's answer goes in detail beside it.
            try:
                self.store.set_fact_detail(self.application_id, f.id, {**f.detail, "lookup": {"service": "PubMed" if pmid else "Crossref", "id": f"PMID {pmid}" if pmid else f"DOI {doi}", "on": date.today().isoformat(), "title": title}})
            except sqlite3.Error as exc:
                raise WorkspaceError(f"Grant Matcher sent {sent}, but could not save what it found ({exc}). It checked {checked} reference{'' if checked == 1 else 's'} before it." + (" What it found for them is saved." if checked else "")) from None
            checked += 1
        if failed:
            rest = len(references) - n - 1
            raise ApiError(f"Grant Matcher could not check {len(failed)} reference{'' if len(failed) == 1 else 's'}. {' '.join(failed)} It checked {checked} reference{'' if checked == 1 else 's'} and saved what it found." + (f" Two lookups in a row failed, so the index is most likely not answering, and Grant Matcher did not try the {rest} reference{'' if rest == 1 else 's'} after them." if streak == 2 and rest else "") + " Nothing was recorded for a reference it could not check. Try again later. For a reference that fails every time, correct its identifier or retire it.")
        return checked

    def write(self, section: str, text: str, parent: int | None) -> Revision:
        self._rule(section)
        current = head(self.store.revisions(self.application_id), section)
        if current is not None and current.id != parent:
            raise StaleEdit(current)
        if current is not None and current.text == text:
            return current
        if (written := self.store.add_revision(self.application_id, section, parent, "applicant", "write", text, only_on_head=True)) is None:
            raise StaleEdit(head(self.store.revisions(self.application_id), section))
        return written

    def restore(self, section: str, revision_id: int, parent: int | None) -> Revision:
        self._rule(section)
        revisions = self.store.revisions(self.application_id)
        old = next((r for r in revisions if r.id == revision_id and r.section == section), None)
        if old is None:
            raise WorkspaceError(f"The {section} section has no revision {revision_id}.")
        current = head(revisions, section)
        if current.id != parent:
            raise StaleEdit(current)
        if current.id == old.id:
            return current
        if (restored := self.store.add_revision(self.application_id, section, old.id, "applicant", "write", old.text, only_on_head=True, head=current.id)) is None:
            raise StaleEdit(head(self.store.revisions(self.application_id), section))
        return restored

    def sign(self, section: str, signer: str, revision_id: int, acknowledge: bool = False) -> Signoff:
        view = self.view()
        s = view.section(section)
        if s.revision_id is None:
            raise NotReady(f"The {s.rule.title} has no text yet. Write it and save it before you sign off.")
        if not s.text.strip():
            raise NotReady(f"The {s.rule.title} holds no text. Write it and save it before you sign off.")
        if s.revision_id != revision_id:
            raise StaleEdit(next(r for r in view.log if r.id == s.revision_id))
        if not signer.strip():
            raise NotReady("Type your name to sign off.")
        if errors := tuple(f for f in s.findings if f.severity == "error"):
            raise NotReady(f"The {s.rule.title} cannot be signed off while an error stands. Fix each error and save, then sign off.", errors)
        if (drafted := tuple(f for f in s.findings if f.code == "mostly-drafted")) and not acknowledge:
            raise NotReady("A model drafted or revised most of this section. Confirm that you have rewritten what you needed to and that it states your own ideas.", drafted)
        digest = hashlib.sha256(s.text.encode("utf-8")).hexdigest()
        attestation = f"I have read this section. It states my own ideas, and I take responsibility for every statement and reference in it. By Grant Matcher's record, {percent(s.attribution.written_share)} of its words came from a model's draft or revision that I accepted, and {percent(s.attribution.polished_share)} from a model's polish of my text. Revision {revision_id}, sha256 {digest}."
        return self.store.add_signoff(self.application_id, section, revision_id, signer.strip(), attestation, list(dict.fromkeys(f.code for f in s.findings if f.severity == "warning")), __version__)

    def _waiting(self, calls: list[ModelCall], revisions: list[Revision]) -> list[ModelCall]:
        # A proposal waits while it can still be accepted: not accepted, not discarded, and read from the newest revision of its section.
        accepted = {r.call_id for r in revisions if r.call_id is not None}
        return [c for c in calls if c.purpose in PROPOSALS and c.id not in accepted and getattr(head(revisions, c.section), "id", None) == c.parent_id and not self.store.setting(f"discarded:{c.id}")]

    def _ask(self, section: str, purpose: str, prompt: prompts.Prompt, parent_id: int | None) -> tuple[ModelCall, Completion]:
        # Every call that carries the applicant's text passes here, so that none leaves before the applicant agreed to its host and every reply is logged. Test connection calls the model itself, with its own consent check and no log.
        if self.model is None:
            raise NotReady("Choose a model under Model, and save a key if the provider needs one, first.")
        if not self.store.setting(f"consent:{self.model.host}"):
            raise NotReady(f"Agree to send text to {self.model.host} first.")
        try:
            done = self.model.complete(prompt.system, prompt.user)
        except ModelError as exc:
            self._log(f"{exc} ", section, "failed", self.model.provider, self.model.name, prompt.system, prompt.user, "", parent_id=parent_id)
            raise
        failure = "The reply was cut off at the token limit." if done.truncated else "The model returned no text." if not done.text.strip() else None
        call = self._log("", section, "failed" if failure else purpose, self.model.provider, done.model, prompt.system, prompt.user, done.text, done.input_tokens, done.output_tokens, parent_id=parent_id)
        if failure:
            raise ModelError(f"{failure} Nothing was changed, and the call is in the log.")
        return call, done

    def _log(self, said: str, *call: Any, **more: Any) -> ModelCall:
        # The text has reached the host by now, so a bare database error would hide that it was sent.
        try:
            return self.store.add_call(self.application_id, *call, **more)
        except sqlite3.Error as exc:
            lost = exc
        # A failed call may never have left, and its own message says whether it did.
        raise ModelError(f"{said}{'Grant Matcher also' if said else f'Your text was sent to {self.model.host}, but Grant Matcher'} could not write the call to its log ({lost}), so the AI-use statement will not show this call.")

    def propose(self, section: str, action: Literal["polish", "revise", "draft"], instruction: str = "") -> Proposal:
        rule = self._rule(section)
        if action not in PROPOSALS:
            raise WorkspaceError(f"{action} is not something a model can do to a section. Use polish, revise or draft.")
        if (action == "draft" and rule.model != "draft") or rule.model == "none":
            raise NotReady(f"A model may not {action} the {rule.title}." + (" It may polish or revise it." if rule.model == "edit" else ""))
        current = head(self.store.revisions(self.application_id), section)
        live = [f for f in self.store.facts(self.application_id) if f.retired_at is None and f.kind in rule.needs + rule.uses]
        if action == "draft" and (gaps := [k for k in rule.needs if k not in {f.kind for f in live}]):
            raise NotReady(f"The {rule.title} needs {', '.join(gaps)} before a model can draft it. Add them under Your inputs, or with apply add.")
        if action != "draft" and (current is None or not current.text.strip()):
            raise NotReady(f"The {rule.title} has no text to {action} yet. Write it and save it first.")
        if action == "revise" and not instruction.strip():
            raise NotReady("Say what to change before you ask for a revision.")
        if action == "draft":
            requirements = tuple(self.store.requirements(self.application_id))
            prompt = prompts.draft(rule, _limit(rule, requirements), requirements, live, _profile(self.store))
        else:
            prompt = prompts.polish(current.text, rule) if action == "polish" else prompts.revise(current.text, instruction.strip(), rule, live)
        call, _ = self._ask(section, action, prompt, getattr(current, "id", None))
        return self._proposal(call)

    def review(self, section: str) -> Review:
        rule = self._rule(section)
        current = head(self.store.revisions(self.application_id), section)
        if current is None or not current.text.strip():
            raise NotReady(f"The {rule.title} has no text to review yet. Write it and save it first.")
        factors = GRANT_TYPES[self._application().grant_type].factors
        # A database that cannot hold the review would waste the call, so it is refused before the text leaves.
        self.store.writable("reviews")
        # The reviewer reads the section alone, so its read is independent of the inputs and prompts that wrote it.
        call, done = self._ask(section, "review", prompts.review(current.text, rule, factors, self.store.requirements(self.application_id)), current.id)
        try:
            review = replace(prompts.parse_review(done.text, current.text, factors), revision_id=current.id, model=done.model)
        except ModelError as exc:
            raise ModelError(f"{exc} Grant Matcher could not read the review and saved nothing, and the call is in the log.") from None
        try:
            self.store.add_review(self.application_id, current.id, call.id, review)
        except sqlite3.Error as exc:
            raise ModelError(f"Your text was sent to {self.model.host} and the call is in the log, but Grant Matcher could not save the review ({exc}).") from None
        return review

    def _proposal(self, call: ModelCall) -> Proposal:
        app, store = self._application(), self.store
        revisions, facts, rule = store.revisions(app.id), tuple(f for f in store.facts(app.id) if f.retired_at is None), self._rule(call.section)
        # The words are attributed as they would be once accepted, so the checks see which of them a model wrote.
        accepted = Revision(max((r.id for r in revisions), default=0) + 1, call.section, call.parent_id, "model", call.purpose, call.response, call.id, call.created_at)
        findings = check_section(call.response, rule, _limit(rule, tuple(store.requirements(app.id))), GRANT_TYPES[app.grant_type].page, facts, _grounding(facts, _profile(store), revisions, store.announcement(app.opportunity_number)), attribution([*revisions, accepted], accepted.id))
        return Proposal(call.id, call.section, call.purpose, call.parent_id, call.response, findings)

    def _call(self, call_id: int) -> ModelCall:
        if (call := next((c for c in self.store.calls(self.application_id) if c.id == call_id), None)) is None:
            raise WorkspaceError(f"Application {self.application_id} has no model call {call_id}.")
        if call.purpose not in PROPOSALS:
            raise WorkspaceError(f"Call {call_id} is {'an' if call.purpose[0] in 'aeiou' else 'a'} {call.purpose} call, not a proposal for a section, so it cannot be accepted or discarded.")
        return call

    def accept(self, call_id: int, edited: str | None = None) -> Revision:
        call, revisions = self._call(call_id), self.store.revisions(self.application_id)
        if (model := next((r for r in revisions if r.call_id == call_id), None)) is not None:
            # The applicant's edit was written with the model's text and carries its time.
            done = next((r for r in revisions if r.parent_id == model.id and r.author == "applicant" and r.created_at == model.created_at), model)
            if head(revisions, call.section).id != done.id:
                raise WorkspaceError(f"Proposal {call_id} was accepted earlier as revision {done.id}, and the section has changed since.")
            # Edits that differ from what the first accept wrote would otherwise be dropped with a success.
            if edited is not None and edited != done.text:
                raise StaleEdit(head(revisions, call.section))
            return done
        if self.store.setting(f"discarded:{call_id}"):
            raise WorkspaceError(f"You discarded proposal {call_id}. Ask the model again for a new one.")
        current = head(revisions, call.section)
        if getattr(current, "id", None) != call.parent_id:
            raise StaleEdit(current)
        then = edited if edited is not None and edited != call.response else None
        if (written := self.store.add_revision(self.application_id, call.section, call.parent_id, "model", call.purpose, call.response, call.id, only_on_head=True, then=then)) is None:
            raise StaleEdit(head(self.store.revisions(self.application_id), call.section))
        return written

    def discard(self, call_id: int) -> None:
        self._call(call_id)
        if any(r.call_id == call_id for r in self.store.revisions(self.application_id)):
            raise WorkspaceError(f"Proposal {call_id} is already accepted. Restore an earlier revision to undo it.")
        self.store.set_setting(f"discarded:{call_id}", datetime.now(timezone.utc).replace(tzinfo=None).isoformat())

    def pending(self, section: str) -> Proposal | None:
        self._rule(section)
        waiting = [c for c in self._waiting(self.store.calls(self.application_id), self.store.revisions(self.application_id)) if c.section == section]
        return self._proposal(waiting[-1]) if waiting else None

    def delete(self) -> None:
        self.store.delete_application(self.application_id)

    def set_disclosure(self, on: bool) -> None:
        self.store.set_disclosure(self.application_id, on)

    def export(self, out_dir: Path) -> Path:
        view, out_dir = self.view(), Path(out_dir).resolve()
        app, signoffs = view.application, self.store.signoffs(self.application_id)
        out_dir.mkdir(parents=True, exist_ok=True)
        titles = {s.rule.key: s.rule.title for s in view.sections}
        for s in view.sections:
            final = s.state == "final"
            (out_dir / f"{'' if final else 'DRAFT-'}{s.rule.key}.md").write_text(f"# {s.rule.title}\n\n{s.text}\n", encoding="utf-8")
            # A file from an earlier export would otherwise stand beside this one under the other name.
            (out_dir / f"{'DRAFT-' if final else ''}{s.rule.key}.md").unlink(missing_ok=True)
        # NIH names no field for the statement, so it is a file of its own, and one from an earlier export goes when the toggle is off.
        if view.disclosure:
            (out_dir / "ai-use-statement.md").write_text(view.disclosure + "\n", encoding="utf-8")
        else:
            (out_dir / "ai-use-statement.md").unlink(missing_ok=True)
        lines = [f"# Requirements for {app.opportunity_number} ({view.grant_type.code})", "", "## Standing rules", ""]
        lines += [f"- {s.rule.title}. At most {describe(s.rule.limit)}." + (f" You confirmed the announcement's limit of {describe(s.limit)}." if s.limit != s.rule.limit else "") for s in view.sections]
        lines += ["", "Sources:", ""] + [f"- {src.url} (read on {src.read_on})" for src in view.grant_type.sources]
        lines += ["", "## From the announcement", ""] + ([f"- {r.text} ({DECISIONS[r.confirmed]}). The announcement says \"{' '.join(r.quote.split())}\"" for r in view.requirements] or ["- None found." if view.announcement else "- The announcement has not been fetched."])
        (out_dir / "requirements.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        log = [f"# Provenance log for {app.opportunity_number} ({view.grant_type.code})", "", f"Exported by Grant Matcher {__version__}.", "", "## Revisions", ""]
        log += [f"- Revision {r.id}. {titles.get(r.section, r.section)}. {r.author} {r.action}, parent {r.parent_id or 'none'}, at {r.created_at.isoformat(timespec='seconds')} UTC. {len(r.text.split())} words." for r in view.log] or ["- None."]
        a = view.announcement
        log += ["", "## Announcement", "", f"- From {ORIGINS[a.origin]} at {a.url}, fetched on {a.fetched_at:%Y-%m-%d}. SHA-256 {a.sha256}." if a else "- Not fetched."]
        log += ["", "## Inputs", ""] + ([f"- Input {f.id}. {f.kind}{f', key {f.label}' if f.label else ''}. " + (f"Retired on {f.retired_at:%Y-%m-%d}." if f.retired_at else "In use.") for f in self.store.facts(self.application_id)] or ["- None."])
        log += ["", "## Sign-offs", ""]
        log += [f"- {titles.get(s.section, s.section)}, revision {s.revision_id}, signed by {s.signer} at {s.signed_at.isoformat(timespec='seconds')} UTC with Grant Matcher {s.tool_version}. {'The warnings that stood were ' + ', '.join(s.findings) + '.' if s.findings else 'No warning stood.'} {s.attestation}" for s in signoffs] or ["- None."]
        (out_dir / "provenance-log.md").write_text("\n".join(log) + "\n", encoding="utf-8")
        return out_dir
