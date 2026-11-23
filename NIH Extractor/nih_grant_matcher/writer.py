from __future__ import annotations
import hashlib
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from . import __version__
from .announcement import Announcement, Requirement, fetch_announcement, parse_requirements, quoted_in
from .checks import check_section
from .clients import ApiError
from .models import Application, Attribution, Fact, Finding, Model, Opportunity, Revision, Signoff
from .profile import BUILTIN_PROFILE, Profile, ProfileError
from .provenance import attribution, head, section_state, share
from .rules import FACT_KINDS, GRANT_TYPES, GrantType, Limit, SectionRule, grant_types_for
from .store import OpportunityStore

DECISIONS = {None: "not yet decided", True: "confirmed", False: "rejected"}
ORIGINS = {"nih-guide": "the NIH Guide", "grants.gov": "Grants.gov"}
NO_SECTION_IV = "Grant Matcher found no Section IV in this text and read no requirement from it. The standing rules apply."
DROPPED = "Your decision on {} was dropped, because the new text no longer has the sentence it came from."

class NotReady(Exception):
    def __init__(self, reason: str, findings: tuple[Finding, ...] = ()) -> None:
        super().__init__(reason)
        self.reason, self.findings = reason, findings

class StaleEdit(Exception):
    def __init__(self, head: Revision) -> None:
        super().__init__(f"The {head.section} section changed after you opened it, and revision {head.id} is the newest. Read it before you save or sign.")
        self.head = head

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
        return self.announcement is not None and not self.announcement.section("IV")
    def section(self, key: str) -> SectionView:
        for s in self.sections:
            if s.rule.key == key:
                return s
        raise ValueError(f"This application has no section {key}. Its sections are {', '.join(s.rule.key for s in self.sections)}.")

def describe(limit: Limit) -> str:
    return f"{limit.amount:g} {limit.unit[:-1] if limit.amount == 1 else limit.unit}"

def _percent(value: float) -> int:
    return round(value * 100)

def _profile(store: OpportunityStore) -> Profile:
    # The dashboard already says that the saved profile cannot be read, and an application can still be started and checked without it.
    try:
        return store.profile()
    except ProfileError:
        return BUILTIN_PROFILE

def _reparse(store: OpportunityStore, app_id: int, announcement: Announcement) -> list[Requirement]:
    same = lambda r: (r.kind, r.section, r.text)
    decided = [r for r in store.requirements(app_id) if r.origin == "parsed" and r.confirmed is not None]
    # A decision moves to the newly parsed requirement that says the same thing, while the sentence it was made on is still in the text.
    carried = {same(r): r.confirmed for r in decided if quoted_in(r.quote, announcement.text)}
    parsed = {same(r): r for r in parse_requirements(announcement)}
    store.replace_requirements(app_id, "parsed", [replace(r, confirmed=carried.get(key)) for key, r in parsed.items()])
    return [r for r in decided if same(r) not in carried or same(r) not in parsed]

def _rules(app: Application) -> tuple[SectionRule, ...]:
    return tuple(s for s in GRANT_TYPES[app.grant_type].sections if app.resubmission or not s.resubmission_only)

class Workspace:
    def __init__(self, store: OpportunityStore, application_id: int, model: Model | None = None) -> None:
        app = store.application(application_id)
        if app is None:
            raise ValueError(f"{store.db_path} has no application {application_id}.")
        self.store, self.application_id, self.model = store, application_id, model
        # A close date is never before date.min, so a notice that has closed is found too, with its Grants.gov id.
        self.opportunity = next((s.opportunity for s in store.top_scored(limit=-1, today=date.min) if s.opportunity.opportunity_number == app.opportunity_number), None)

    @classmethod
    def start(cls, store: OpportunityStore, opportunity: Opportunity, grant_type: str, resubmission: bool = False, model: Model | None = None) -> Workspace:
        covered = [f"{g.funder}:{g.code}" for g in grant_types_for(opportunity)]
        if grant_type not in covered:
            raise ValueError(f"Grant Matcher does not write {opportunity.opportunity_number} as {grant_type}." + (f" It can write it as {', '.join(covered)}." if covered else ""))
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
            raise ValueError(f"{self.store.db_path} has no application {self.application_id}.")
        return app

    def _check_section(self, key: str) -> None:
        if key not in (keys := [s.key for s in _rules(self._application())]):
            raise ValueError(f"This application has no section {key}. Its sections are {', '.join(keys)}.")

    def view(self) -> ApplicationView:
        app, store = self._application(), self.store
        grant_type, announcement = GRANT_TYPES[app.grant_type], store.announcement(app.opportunity_number)
        requirements, facts = tuple(store.requirements(app.id)), tuple(f for f in store.facts(app.id) if f.retired_at is None)
        revisions, signoffs, profile = store.revisions(app.id), store.signoffs(app.id), _profile(store)
        grounding = "\n".join([*(f.text for f in facts), profile.research_summary, profile.expertise, profile.resources, *(r.text for r in revisions if r.author == "applicant"), announcement.text if announcement else ""])
        notices, kinds, sections = [], {f.kind for f in facts}, []
        for rule in _rules(app):
            # A limit in pages cannot replace a limit in lines or sentences.
            confirmed = [r.limit for r in requirements if r.kind == "limit" and r.confirmed and r.section == rule.key and r.limit and r.limit.unit == rule.limit.unit]
            limit = min(confirmed, key=lambda l: l.amount, default=rule.limit)
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
            sections.append(SectionView(rule, limit, text, current.id if current else None, state, tuple(k for k in rule.needs if k not in kinds), findings, share(words)))
        year = datetime.now(timezone.utc).year
        if app.created_at.year == year and (n := sum(a.created_at.year == year and a.id <= app.id for a in store.applications())) >= 6:
            notices.append(f"This is application {n} that Grant Matcher has started in {year}. NIH accepts six per investigator per calendar year (NOT-OD-25-132). Grant Matcher counts only its own.")
        return ApplicationView(app, grant_type, announcement, requirements, facts, tuple(sections), tuple(revisions), tuple(notices), "")

    def fetch_announcement(self, guide: Any = None, grants: Any = None) -> tuple[Announcement, list[Requirement]]:
        app = self._application()
        # Without a saved record the fetch goes by the number saved with the application.
        opportunity = self.opportunity or Opportunity("", app.opportunity_number, app.title, "", "", "")
        announcement = fetch_announcement(opportunity, guide, grants)
        # Grants.gov is the official source, and the Guide can serve an older text when Grants.gov does not answer.
        if (saved := self.store.announcement(app.opportunity_number)) is not None and saved.origin == "grants.gov" and announcement.origin == "nih-guide":
            raise ApiError(f"Grant Matcher could not get the announcement for {app.opportunity_number} from Grants.gov this time, so it kept the copy it saved from there on {saved.fetched_at:%Y-%m-%d}. The NIH Guide's text can be older.")
        self.store.save_announcement(announcement)
        # The announcement is saved once for its number, so every application for that number reads it again.
        dropped = {other.id: _reparse(self.store, other.id, announcement) for other in self.store.applications() if other.opportunity_number == app.opportunity_number}
        return announcement, dropped[app.id]

    def decide(self, requirement_id: int, confirmed: bool) -> None:
        if requirement_id not in {r.id for r in self.store.requirements(self.application_id)}:
            raise ValueError(f"Application {self.application_id} has no requirement {requirement_id}.")
        self.store.decide_requirement(requirement_id, confirmed)

    def add_fact(self, kind: str, text: str, label: str = "", detail: dict | None = None) -> Fact:
        if kind not in FACT_KINDS:
            raise ValueError(f"{kind} is not a kind of input. Use one of {', '.join(FACT_KINDS)}.")
        if not text.strip():
            raise ValueError("An input needs text.")
        self._application()
        return self.store.add_fact(self.application_id, kind, text.strip(), label.strip(), detail)

    def retire_fact(self, fact_id: int) -> None:
        if fact_id not in {f.id for f in self.store.facts(self.application_id)}:
            raise ValueError(f"Application {self.application_id} has no input {fact_id}.")
        self.store.retire_fact(fact_id)

    def write(self, section: str, text: str, parent: int | None) -> Revision:
        self._check_section(section)
        current = head(self.store.revisions(self.application_id), section)
        if current is not None and current.id != parent:
            raise StaleEdit(current)
        if current is not None and current.text == text:
            return current
        if (written := self.store.add_revision(self.application_id, section, parent, "applicant", "write", text, only_on_head=True)) is None:
            raise StaleEdit(head(self.store.revisions(self.application_id), section))
        return written

    def restore(self, section: str, revision_id: int) -> Revision:
        self._check_section(section)
        revisions = self.store.revisions(self.application_id)
        old = next((r for r in revisions if r.id == revision_id and r.section == section), None)
        if old is None:
            raise ValueError(f"The {section} section has no revision {revision_id}.")
        current = head(revisions, section)
        return current if current is not None and current.id == old.id else self.store.add_revision(self.application_id, section, old.id, "applicant", "write", old.text)

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
        attestation = f"I have read this section. It states my own ideas, and I take responsibility for every statement and reference in it. By Grant Matcher's record, {_percent(s.attribution.written_share)} percent of its words came from a model's draft or revision that I accepted, and {_percent(s.attribution.polished_share)} percent from a model's polish of my text. Revision {revision_id}, sha256 {digest}."
        return self.store.add_signoff(self.application_id, section, revision_id, signer.strip(), attestation, list(dict.fromkeys(f.code for f in s.findings if f.severity == "warning")), __version__)

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
