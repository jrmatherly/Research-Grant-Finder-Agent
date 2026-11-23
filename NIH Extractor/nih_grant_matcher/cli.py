from __future__ import annotations
import argparse, json, sqlite3, sys
from pathlib import Path
from .agents import DigestAgent, NihContextAgent
from .clients import ApiError, NihGuideClient, NihReporterClient
from .config import TERM_RARITY_PATH, MatcherConfig
from .excel import write_excel
from .normalizer import normalize_nih_guide
from .profile import ProfileError, from_export, to_export
from .rules import FACT_KINDS
from .scoring import document_frequencies
from .store import OpportunityStore, ReadOnlyProfile
from .workflow import fetch_score_opportunities, rescore_saved
from .writer import DECISIONS, NO_SECTION_IV, ORIGINS, NotReady, StaleEdit, Workspace, describe

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
    for name, text in (("fetch", "Fetch the full announcement and the requirements it adds."), ("requirements", "Print the standing rules and the announcement's requirements."), ("check", "Print each section with its state and findings. Exit 1 while an error stands.")):
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
    export = apply.add_parser("export", help="Write the sections, the requirements and the provenance log to a folder.")
    export.add_argument("id", type=int)
    export.add_argument("--out", required=True)
    delete = apply.add_parser("delete", help="Delete an application and everything logged for it.")
    delete.add_argument("id", type=int)
    delete.add_argument("--yes", action="store_true", help="Confirm the delete.")
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
    raise ValueError(args.command)

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
            print(f"{r.id}  {DECISIONS[r.confirmed]}  {r.text}")
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
    elif args.action == "sign":
        signed = ws.sign(args.section, args.signer, ws.view().section(args.section).revision_id or 0, args.acknowledge)
        print(f"Signed off {args.section} at revision {signed.revision_id}.")
        print(signed.attestation)
    elif args.action == "export":
        print(f"Wrote the application to {ws.export(Path(args.out))}.")
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
