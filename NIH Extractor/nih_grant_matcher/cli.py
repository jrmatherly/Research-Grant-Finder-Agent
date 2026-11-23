from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from .agents import DigestAgent, NihContextAgent
from .clients import NihGuideClient, NihReporterClient
from .config import TERM_RARITY_PATH, MatcherConfig
from .excel import write_excel
from .normalizer import normalize_nih_guide
from .scoring import document_frequencies
from .store import OpportunityStore
from .workflow import fetch_score_opportunities, rescore_saved

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find NIH grant opportunities relevant to ML/data analysis.")
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
    return parser

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
