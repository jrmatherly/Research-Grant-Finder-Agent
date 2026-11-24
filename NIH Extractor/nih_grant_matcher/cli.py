from __future__ import annotations
import argparse, json, sqlite3, sys
from datetime import datetime, timezone
from pathlib import Path
from . import keys
from .agents import DigestAgent, NihContextAgent
from .clients import ApiError, NihGuideClient, NihReporterClient, one_line
from .config import TERM_RARITY_PATH, MatcherConfig
from .excel import write_excel
from .llm import PROVIDERS, cautions, checked_base_url, checked_workspace, chosen, connect, host_of, list_models, missing, workspace
from .normalizer import normalize_nih_guide
from .profile import ProfileError, from_export, to_export
from .rules import FACT_KINDS, GRANT_TYPES
from .scoring import document_frequencies
from .store import OpportunityStore, ReadOnlyProfile
from .workflow import fetch_score_opportunities, rescore_saved
from .writer import DECISIONS, DROPPED, NO_SECTION_IV, ORIGINS, STALE_PROPOSAL, NotReady, StaleEdit, Workspace, describe, dropped_points, lookup_line, read_summary, score_line

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find and rank NIH grant opportunities with an applicant profile.")
    parser.add_argument("--db", default="data/grants.sqlite3", help="SQLite database path.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Fetch, score, save, and write a digest.")
    run.add_argument("--source", choices=("nih-guide", "grants.gov", "both"), default="nih-guide", help="Opportunity source. Defaults to NIH Guide.")
    run.add_argument("--agency", action="append", help="Grants.gov agency code. Used only with --source grants.gov or both.")
    run.add_argument("--status", action="append", help="Grants.gov opportunity status. Defaults to posted and forecasted.")
    run.add_argument("--keyword", default="", help="Optional keyword search.")
    run.add_argument("--limit", type=int, default=500, help="Maximum rows to request per source.")
    run.add_argument("--out", default="digests/latest.md", help="Markdown digest path.")
    run.add_argument("--min-score", type=float, default=0.0, help="Minimum score included in digest.")
    digest = sub.add_parser("digest", help="Write a digest from saved opportunities.")
    digest.add_argument("--out", default="digests/latest.md")
    digest.add_argument("--min-score", type=float, default=0.0)
    digest.add_argument("--limit", type=int, default=100)
    excel = sub.add_parser("excel", help="Write saved ranked opportunities to an Excel .xlsx file.")
    excel.add_argument("--out", default="outputs/nih_grant_opportunities.xlsx")
    excel.add_argument("--min-score", type=float, default=0.0)
    excel.add_argument("--limit", type=int, default=500)
    context = sub.add_parser("reporter-context", help="Search NIH RePORTER for funded project context.")
    context.add_argument("--term", required=True)
    context.add_argument("--limit", type=int, default=10)
    rarity = sub.add_parser("rarity-table", help="Rebuild the word-rarity table that similarity scoring uses, from expired NIH Guide opportunities.")
    rarity.add_argument("--rows", type=int, default=3000, help="Expired opportunities to read.")
    rarity.add_argument("--out", default=str(TERM_RARITY_PATH))
    profile = sub.add_parser("profile", help="Show, export, import, or reset the applicant profile that ranking uses.")
    actions = profile.add_subparsers(dest="action", required=True)
    actions.add_parser("show", help="Print the profile in use.")
    actions.add_parser("export", help="Write the profile in use to a file.").add_argument("--out", required=True)
    actions.add_parser("import", help="Save a profile from an exported file.").add_argument("path")
    actions.add_parser("reset", help="Go back to the built-in profile.")
    apply = sub.add_parser("apply", help="Start, write, check, sign off and export an application.").add_subparsers(dest="action", required=True)
    apply.add_parser("list", help="List the applications in the database.")
    start = apply.add_parser("start", help="Start an application for a saved opportunity.")
    start.add_argument("number", help="The opportunity number, such as PAR-25-123.")
    start.add_argument("--type", required=True, help="The activity code, such as R21.")
    start.add_argument("--resubmission", action="store_true", help="Add the Introduction of a resubmission.")
    for name, text in (("fetch", "Fetch the full announcement and the requirements it adds."), ("extract", "Ask the model you chose to read Sections I, IV and V of the fetched announcement and list what they ask for. Nothing counts until you confirm it."), ("requirements", "Print the standing rules and the announcement's requirements."), ("check", "Print each section with its state and findings. Exit 1 while an error stands."), ("verify", "Check that each reference you listed exists. Sends each PMID to NCBI (PubMed) and each DOI without a PMID to Crossref, and nothing else.")):
        apply.add_parser(name, help=text).add_argument("id", type=int)
    add = apply.add_parser("add", help="Add one of your inputs, such as an aim or a reference.")
    add.add_argument("id", type=int)
    add.add_argument("--kind", required=True, help=f"One of {', '.join(FACT_KINDS)}.")
    given = add.add_mutually_exclusive_group(required=True)
    given.add_argument("--text")
    given.add_argument("--file", help="A UTF-8 text file that holds the input.")
    add.add_argument("--label", default="", help="The key of a reference, which a section cites as [@key].")
    write = apply.add_parser("write", help="Save a section from a UTF-8 text file as the newest revision.")
    write.add_argument("id", type=int)
    write.add_argument("section")
    write.add_argument("--file", required=True)
    sign = apply.add_parser("sign", help="Sign off the newest revision of a section.")
    sign.add_argument("id", type=int)
    sign.add_argument("section")
    sign.add_argument("--signer", required=True)
    sign.add_argument("--acknowledge", action="store_true", help="Confirm that you rewrote a section that a model mostly drafted.")
    export = apply.add_parser("export", help="Write the sections, the requirements, the provenance log and, while it is on, the AI-use statement to a folder.")
    export.add_argument("id", type=int)
    export.add_argument("--out", required=True)
    polish = apply.add_parser("polish", help="Ask the model you chose to polish the newest revision of a section. Nothing changes until you accept.")
    revise = apply.add_parser("revise", help="Ask the model you chose to revise the newest revision of a section. Nothing changes until you accept.")
    draft = apply.add_parser("draft", help="Ask the model you chose to draft a section from your inputs. Nothing changes until you accept.")
    review = apply.add_parser("review", help="Ask the model you chose to score the newest revision of a section against NIH's review factors. It sees only the section and the review criteria you confirmed.")
    for asked in (polish, revise, draft, review):
        asked.add_argument("id", type=int)
        asked.add_argument("section")
    revise.add_argument("--instruction", required=True, help="What to change.")
    for name, text in (("accept", "Make a model's proposal the newest revision of its section."), ("discard", "Set a model's proposal aside. It stays in the log.")):
        proposal = apply.add_parser(name, help=text)
        proposal.add_argument("id", type=int)
        proposal.add_argument("call", type=int, help="The number of the proposal, which polish, revise and draft print.")
    disclosure = apply.add_parser("disclosure", help="Turn the AI-use statement in the export on or off, and print it.")
    disclosure.add_argument("id", type=int)
    toggle = disclosure.add_mutually_exclusive_group(required=True)
    toggle.add_argument("--on", action="store_true")
    toggle.add_argument("--off", action="store_true")
    delete = apply.add_parser("delete", help="Delete an application and everything logged for it.")
    delete.add_argument("id", type=int)
    delete.add_argument("--yes", action="store_true", help="Confirm the delete.")
    models = sub.add_parser("models", help="Choose the model that helps you write, list the provider's models, or agree to send your text to its host.")
    models.add_argument("--provider", choices=tuple(PROVIDERS))
    models.add_argument("--model", help="A name from the list that this command prints.")
    models.add_argument("--base-url", help="The server's address, for the compatible provider. For example http://localhost:11434/v1.")
    models.add_argument("--workspace", help="For a Claude key that is not scoped to one workspace: the ID of the workspace to use, from platform.claude.com/settings/workspaces. An empty value clears it.")
    models.add_argument("--consent", action="store_true", help="Agree to send your text to the provider's host.")
    return parser

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args)
    except ApiError as exc:
        # A failed request is not a bug, so it gets one line and no traceback.
        print(f"Request failed: {exc}", file=sys.stderr)
        return 1
    except (NotReady, StaleEdit) as exc:
        print(exc, file=sys.stderr)
        for finding in getattr(exc, "findings", ()):
            print(f"  {finding.severity}  {finding.code}  {finding.message}", file=sys.stderr)
        return 1
    except ProfileError as exc:
        print(exc if isinstance(exc, ReadOnlyProfile) else f"Profile not valid: {exc}", file=sys.stderr)
        return 1
    except keys.UnreadableKey as exc:
        print(exc, file=sys.stderr)
        return 1
    except (OSError, UnicodeDecodeError) as exc:
        print(f"File error: {exc}", file=sys.stderr)
        return 1
    except sqlite3.Error as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 1

def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "run":
        return _run(args)
    if args.command == "digest":
        return _digest(args)
    if args.command == "excel":
        return _excel(args)
    if args.command == "reporter-context":
        return _reporter_context(args)
    if args.command == "rarity-table":
        return _rarity_table(args)
    if args.command == "profile":
        return _profile(args)
    if args.command == "apply":
        return _apply(args)
    if args.command == "models":
        return _models(args)
    raise ValueError(args.command)

def _models(args: argparse.Namespace) -> int:
    try:
        base_url = checked_base_url(args.base_url) if args.base_url else None
        ws = None if args.workspace is None else checked_workspace(args.workspace)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    store = OpportunityStore(args.db)
    try:
        if args.provider:
            store.set_setting("llm.provider", args.provider)
        # Naming a provider, even the one already chosen, resets the model to that provider's default, so one provider's model is never sent to another.
        if args.provider or args.model:
            store.set_setting("llm.model", args.model or "")
        if base_url:
            store.set_setting("llm.base_url", base_url)
        if ws is not None:
            store.set_setting("llm.workspace", ws)
        picked = chosen(store)
        if picked is None:
            print(f"No provider is chosen. Choose one with models --provider and one of {', '.join(PROVIDERS)}.", file=sys.stderr)
            return 1
        provider, name, base_url = picked
        host = host_of(base_url)
        if args.consent:
            store.set_setting(f"consent:{host}", datetime.now(timezone.utc).replace(tzinfo=None).isoformat())
        print(f"Provider {provider.name}. Model {name or 'not chosen'}. Your text goes to {host}" + (". You agreed to that." if store.setting(f"consent:{host}") else ", once you agree with models --consent."))
        for caution in cautions(provider, base_url):
            print(caution)
        if provider.name == "claude" and workspace(store):
            print(f"Workspace {workspace(store)}.")
        key = keys.get(provider, store.db_path.parent)
        if provider.needs_key and not key:
            print(f"No key. Set {provider.key_env}, or {provider.key_env}_FILE to a file that holds it, or save one in the dashboard.", file=sys.stderr)
            return 1
        print(f"Key: {keys.where(provider, store.db_path.parent)}." if key else "No key, which this provider does not need.")
        for listed in list_models(provider, base_url, key, workspace(store)):
            print(listed)
    finally:
        store.close()
    return 0

def _run(args: argparse.Namespace) -> int:
    config = MatcherConfig(agencies=tuple(args.agency or ("HHS-NIH11",)), statuses=tuple(args.status or ("posted", "forecasted")), rows=args.limit, min_digest_score=args.min_score, db_path=args.db)
    scored, fetched, capped = fetch_score_opportunities(config, source=args.source, keyword=args.keyword)
    if capped:
        print(f"A source returned {args.limit} rows, which is the --limit, and may hold more. Raise --limit and run again.", file=sys.stderr)
    store = OpportunityStore(config.db_path)
    try:
        saved = store.upsert_many(scored)
        rescore_saved(store)
        digest_path = DigestAgent(store, min_score=args.min_score).write(args.out, limit=max(100, args.limit))
    finally:
        store.close()
    print(f"Fetched {fetched} opportunities from {args.source}.")
    print(f"Saved {saved} current NIH/HHS opportunities to {config.db_path}.")
    print(f"Wrote digest to {digest_path}.")
    return 0

def _digest(args: argparse.Namespace) -> int:
    store = OpportunityStore(args.db)
    try:
        rescore_saved(store)
        digest_path = DigestAgent(store, min_score=args.min_score).write(args.out, limit=args.limit)
    finally:
        store.close()
    print(f"Wrote digest to {digest_path}.")
    return 0

def _excel(args: argparse.Namespace) -> int:
    store = OpportunityStore(args.db)
    try:
        rescore_saved(store)
        items = store.top_scored(min_score=args.min_score, limit=args.limit)
        output_path = write_excel(items, args.out, min_score=args.min_score)
    finally:
        store.close()
    print(f"Wrote Excel file to {output_path}.")
    return 0

def _reporter_context(args: argparse.Namespace) -> int:
    print(json.dumps(NihContextAgent(NihReporterClient()).similar_funded_projects(args.term, limit=args.limit), indent=2))
    return 0

def _profile(args: argparse.Namespace) -> int:
    store = OpportunityStore(args.db)
    try:
        if args.action == "show":
            print(json.dumps(json.loads(to_export(store.profile()))["profile"], indent=2))
        elif args.action == "export":
            Path(args.out).write_text(to_export(store.profile()) + "\n", encoding="utf-8")
            print(f"Wrote the profile to {args.out}.")
        elif args.action == "import":
            store.save_profile(from_export(Path(args.path).read_text(encoding="utf-8")))
            print(f"Saved the profile from {args.path} to {args.db}.")
        else:
            store.save_profile(None)
            print(f"Reset {args.db} to the built-in profile.")
    finally:
        store.close()
    return 0

def _apply(args: argparse.Namespace) -> int:
    store = OpportunityStore(args.db)
    try:
        return _apply_action(store, args)
    except (ProfileError, UnicodeDecodeError):
        raise
    except ValueError as exc:
        # An unknown application, section, kind or grant type is the user's mistake, so it gets one line.
        print(exc, file=sys.stderr)
        return 1
    finally:
        store.close()

def _apply_action(store: OpportunityStore, args: argparse.Namespace) -> int:
    if args.action == "list":
        for app in store.applications():
            print(f"{app.id}  {app.opportunity_number}  {app.grant_type.split(':')[-1]}{'  resubmission' if app.resubmission else ''}  {app.title}")
        if not store.applications():
            print("No applications yet. Start one with apply start NUMBER --type CODE.")
        return 0
    if args.action == "start":
        opportunity = next((s.opportunity for s in store.top_scored(limit=-1) if s.opportunity.opportunity_number == args.number), None)
        if opportunity is None:
            raise ValueError(f"{args.db} holds no open opportunity {args.number}. Run a search that finds it first.")
        ws = Workspace.start(store, opportunity, f"NIH:{args.type}", args.resubmission)
        print(f"Application {ws.application_id} is {args.number} as {args.type}{', a resubmission' if args.resubmission else ''}.")
        return 0
    ws = Workspace(store, args.id)
    if args.action in ("extract", "polish", "revise", "draft", "review"):
        ws.model = connect(store)
        if ws.model is None:
            raise NotReady(f"{missing(store)} Set up the model with the models command, starting with models --provider.")
    if args.action == "fetch":
        (announcement, notes), view = ws.fetch_announcement(), ws.view()
        added = sum(r.confirmed is None for r in view.requirements)
        print(f"Saved the announcement from {ORIGINS[announcement.origin]}. " + (NO_SECTION_IV if view.no_section_iv else f"It adds {added} requirement{'' if added == 1 else 's'} to confirm or reject in the dashboard."))
        for note in notes:
            print(note)
    elif args.action == "requirements":
        view = ws.view()
        for s in view.sections:
            print(f"standing  {s.rule.title}  at most {describe(s.rule.limit)}")
        for r in view.requirements:
            print(f"{r.id}  {DECISIONS[r.confirmed]}  {r.text}" + (f"  at most {describe(r.limit)}" if r.limit else ""))
        if view.no_section_iv:
            print(NO_SECTION_IV)
        if view.announcement is None:
            print(f"The announcement has not been fetched. Run apply fetch {args.id}.")
    elif args.action == "add":
        text = Path(args.file).read_text(encoding="utf-8") if args.file else args.text
        fact = ws.add_fact(args.kind, text, args.label)
        print(f"Added input {fact.id} under {fact.kind}.")
    elif args.action == "write":
        text, before = Path(args.file).read_text(encoding="utf-8"), ws.view().section(args.section).revision_id
        revision = ws.write(args.section, text, before)
        print(f"The {args.section} section is unchanged at revision {revision.id}." if revision.id == before else f"Saved revision {revision.id} of {args.section}.")
    elif args.action == "check":
        view, blocked = ws.view(), False
        for notice in view.notices:
            print(notice)
        for s in view.sections:
            print(f"{s.rule.key}  {s.state}  {len(s.text.split())} words" + (f"  needs {', '.join(s.gaps)}" if s.gaps else ""))
            for finding in s.findings:
                print(f"  {finding.severity}  {finding.code}  {finding.message}")
            blocked = blocked or any(f.severity == "error" for f in s.findings)
        return 1 if blocked else 0
    elif args.action == "verify":
        checked = ws.verify_references()
        for f in (f for f in ws.view().facts if f.kind == "reference"):
            print(f"{f'[@{f.label}]' if f.label else f'Input {f.id}'}  {lookup_line(f)}")
        print(f"Checked {checked} reference{'' if checked == 1 else 's'} with PubMed or Crossref.")
    elif args.action == "sign":
        signed = ws.sign(args.section, args.signer, ws.view().section(args.section).revision_id or 0, args.acknowledge)
        print(f"Signed off {args.section} at revision {signed.revision_id}.")
        print(signed.attestation)
    elif args.action == "export":
        print(f"Wrote the application to {ws.export(Path(args.out))}.")
    elif args.action == "extract":
        found, dropped = ws.extract_requirements()
        print(f"{read_summary(found)} Confirm or reject each in the dashboard.")
        for r in found:
            print(f"{r.id}  {DECISIONS[r.confirmed]}  {r.text}" + (f"  at most {describe(r.limit)}" if r.limit else ""))
        if dropped:
            print(f"Grant Matcher dropped {dropped} item{'' if dropped == 1 else 's'} of the model's replies. {DROPPED}")
    elif args.action in ("polish", "revise", "draft"):
        proposal = ws.propose(args.section, args.action, getattr(args, "instruction", ""))
        print(f"Proposal {proposal.call_id} for {args.section}. Nothing has changed yet.\n\n{proposal.text}\n")
        for finding in proposal.findings:
            print(f"  {finding.severity}  {finding.code}  {finding.message}")
        print(f"Accept it with apply accept {args.id} {proposal.call_id}, or discard it with apply discard {args.id} {proposal.call_id}.")
    elif args.action == "review":
        review = ws.review(args.section)
        print(f"The model's review of revision {review.revision_id} of {args.section}. It saw only the section and the review criteria you confirmed.")
        for factor in GRANT_TYPES[store.application(args.id).grant_type].factors:
            print(f"  {one_line(score_line(factor, review.scores.get(factor.key)))}")
        for point in review.points:
            print(f"  {point.kind}{f'  {point.factor}' if point.factor else ''}  {one_line(point.text)}\n    \"{one_line(point.quote)}\"")
        if review.dropped:
            print(dropped_points(review))
    elif args.action == "accept":
        try:
            revision = ws.accept(args.call)
        except StaleEdit:
            raise NotReady(STALE_PROPOSAL) from None
        print(f"Accepted proposal {args.call} as revision {revision.id} of {revision.section}.")
    elif args.action == "discard":
        ws.discard(args.call)
        print(f"Discarded proposal {args.call}. It stays in the log.")
    elif args.action == "disclosure":
        ws.set_disclosure(args.on)
        print(ws.view().disclosure if args.on else "The export leaves out the AI-use statement.")
    else:
        if not args.yes:
            print(f"Nothing was deleted. Add --yes to delete application {args.id} and everything logged for it.", file=sys.stderr)
            return 1
        ws.delete()
        print(f"Deleted application {args.id}.")
    return 0

def _rarity_table(args: argparse.Namespace) -> int:
    texts = [normalize_nih_guide(item).searchable_text for item in NihGuideClient().search(rows=args.rows, types="expired")]
    if len(texts) < args.rows // 2:
        print(f"Read {len(texts)} opportunities, fewer than half of the {args.rows} asked for, so the table was not replaced.", file=sys.stderr)
        return 1
    # A word seen in one document is left out to keep the file small. Scoring then treats it as unseen, which weighs it about 8% higher.
    terms = {term: count for term, count in sorted(document_frequencies(texts).items()) if count > 1}
    partial = Path(f"{args.out}.partial")
    partial.write_text(json.dumps({"documents": len(texts), "terms": terms}, separators=(",", ":")) + "\n", encoding="utf-8")
    partial.replace(args.out)
    print(f"Wrote {len(terms)} terms from {len(texts)} opportunities to {args.out}.")
    return 0
