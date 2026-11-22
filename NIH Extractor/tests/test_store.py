from datetime import date
from nih_grant_matcher.models import Opportunity
from nih_grant_matcher.scoring import MLRelevanceScorer
from nih_grant_matcher.store import OpportunityStore

def test_store_upserts_and_reads_scored_opportunity(tmp_path) -> None:
    store = OpportunityStore(tmp_path / "grants.sqlite3")
    opportunity = Opportunity(source_id="abc", opportunity_number="RFA-ABC", title="Machine learning for health", agency_code="HHS-NIH11", agency_name="National Institutes of Health", status="posted", close_date=date(2026, 12, 1), description="Machine learning and predictive models for health data.")
    scored = MLRelevanceScorer().score(opportunity, today=date(2026, 7, 6))
    try:
        store.upsert_scored(scored)
        results = store.top_scored(min_score=0, limit=10, today=date(2026, 7, 6))
    finally:
        store.close()
    assert len(results) == 1
    assert results[0].opportunity.source_id == "abc"
    assert results[0].score == scored.score

def _scored(source_id: str, number: str, close_date: date):
    return MLRelevanceScorer().score(Opportunity(source_id=source_id, opportunity_number=number, title="Machine learning for health", agency_code="HHS-NIH11", agency_name="National Institutes of Health", status="posted", close_date=close_date), today=date(2026, 7, 6))

def _saved_ids(tmp_path, items, expected_saved: int) -> list[str]:
    store = OpportunityStore(tmp_path / "grants.sqlite3")
    try:
        assert store.upsert_many(items) == expected_saved
        return [item.opportunity.source_id for item in store.top_scored(today=date(2026, 7, 6))]
    finally:
        store.close()

def test_store_leaves_out_closed_opportunities(tmp_path) -> None:
    assert _saved_ids(tmp_path, [_scored("old", "RFA-OLD", date(2026, 7, 5)), _scored("new", "RFA-NEW", date(2026, 7, 6))], 2) == ["new"]

def test_store_clears_duplicates_saved_before_the_rule(tmp_path) -> None:
    store = OpportunityStore(tmp_path / "grants.sqlite3")
    close = date(2026, 12, 1)
    try:
        for source_id in ("111", "nih-guide:1"):
            store.conn.execute("INSERT INTO opportunities (source_id, opportunity_number, title, close_date) VALUES (?, 'RFA-1', 't', ?)", (source_id, close.isoformat()))
            store.conn.execute("INSERT INTO scores VALUES (?, 50, 'Medium', '[]', '[]', ?, '2026-07-06T00:00:00')", (source_id, '{"keyword_score": 0, "semantic_score": 0, "nih_score": 0, "urgency_score": 0, "completeness_score": 0, "centrality_score": 0, "generic_penalty": 0}'))
        store.conn.commit()
        assert store.upsert_scored(_scored("222", "RFA-1", close)) is False
        assert [item.opportunity.source_id for item in store.top_scored(today=date(2026, 7, 6))] == ["nih-guide:1"]
    finally:
        store.close()

def test_store_keeps_one_row_per_opportunity_number(tmp_path) -> None:
    close = date(2026, 12, 1)
    assert _saved_ids(tmp_path, [_scored("123", "RFA-1", close), _scored("nih-guide:9", "RFA-1", close), _scored("456", "RFA-1", close)], 2) == ["nih-guide:9"]
