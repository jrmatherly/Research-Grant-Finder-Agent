from __future__ import annotations

import sqlite3
import warnings
from dataclasses import dataclass
from typing import Iterable

from .agents import GrantParserAgent, IngestionAgent, MLRelevanceAgent, NihGuideIngestionAgent
from .clients import GrantsGovClient, NihGuideClient
from .config import MatcherConfig
from .filters import is_current_nih_hhs_opportunity
from .models import Opportunity, ScoredOpportunity
from .scoring import MLRelevanceScorer
from .store import OpportunityStore


@dataclass(frozen=True)
class RunSummary:
    fetched: int
    saved: int
    source: str
    capped: bool = False


def config_for(store: OpportunityStore, base: MatcherConfig | None = None) -> MatcherConfig:
    return store.profile().matcher_config(base)


def fetch_score_opportunities(config: MatcherConfig, source: str = "nih-guide", keyword: str = "") -> tuple[list[ScoredOpportunity], int, bool]:
    parser = GrantParserAgent()
    opportunities: list[Opportunity] = []
    fetched = 0
    # fetched sums the sources, so the limit is compared to each source's own count.
    capped = False

    if source in ("nih-guide", "both"):
        guide_opportunities = NihGuideIngestionAgent(NihGuideClient(), config).ingest(keyword=keyword)
        opportunities.extend(guide_opportunities)
        fetched += len(guide_opportunities)
        capped = capped or len(guide_opportunities) >= config.rows

    if source in ("grants.gov", "both"):
        enriched = IngestionAgent(GrantsGovClient(), config).ingest(keyword=keyword)
        opportunities.extend(parser.parse(hit, detail) for hit, detail in enriched)
        fetched += len(enriched)
        capped = capped or len(enriched) >= config.rows

    # Read the profile after the fetch, so that a failed request leaves no database behind.
    store = OpportunityStore(config.db_path)
    try:
        relevance = MLRelevanceAgent(MLRelevanceScorer(config_for(store, config)))
    finally:
        store.close()
    scored = [relevance.score(opp) for opp in _dedupe_opportunities(opportunities)]
    current = [item for item in scored if is_current_nih_hhs_opportunity(item.opportunity)]
    current.sort(key=lambda item: (-item.score, item.opportunity.close_date is None, item.opportunity.close_date or item.scored_at.date()))
    return current, fetched, capped


def run_and_save(config: MatcherConfig, source: str = "nih-guide", keyword: str = "") -> tuple[list[ScoredOpportunity], RunSummary]:
    scored, fetched, capped = fetch_score_opportunities(config, source=source, keyword=keyword)
    store = OpportunityStore(config.db_path)
    try:
        saved = store.upsert_many(scored)
    finally:
        store.close()
    return scored, RunSummary(fetched=fetched, saved=saved, source=source, capped=capped)


def rescore_saved(store: OpportunityStore) -> None:
    # A saved score goes stale when the scoring rules change, and as the expiration date nears. Scoring needs no network, so score the open rows again before every read.
    scorer = MLRelevanceScorer(config_for(store))
    try:
        store.upsert_many([scorer.score(item.opportunity) for item in store.top_scored(limit=-1)])
    except sqlite3.OperationalError as exc:
        # A read-only database, or one that another program is writing to, can still be read, with the scores it holds. Any other failure, such as a full disk, is an error.
        if exc.sqlite_errorcode & 0xFF not in (sqlite3.SQLITE_READONLY, sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise
        warnings.warn(f"Could not update the saved scores, so they are shown as last saved: {exc}", RuntimeWarning, stacklevel=2)


def load_saved(db_path: str, min_score: float = 0.0, limit: int = 500) -> list[ScoredOpportunity]:
    store = OpportunityStore(db_path)
    try:
        rescore_saved(store)
        return store.top_scored(min_score=min_score, limit=limit)
    finally:
        store.close()


def _dedupe_opportunities(opportunities: Iterable[Opportunity]) -> list[Opportunity]:
    deduped: dict[str, Opportunity] = {}
    for opportunity in opportunities:
        key = opportunity.opportunity_number or opportunity.source_id
        existing = deduped.get(key)
        if existing is None or opportunity.source_id.startswith("nih-guide:"):
            deduped[key] = opportunity
    return list(deduped.values())

