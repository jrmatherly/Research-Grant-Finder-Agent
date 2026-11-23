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

def test_store_replaces_a_grants_gov_row_when_the_guide_row_arrives(tmp_path) -> None:
    close = date(2026, 12, 1)
    assert _saved_ids(tmp_path, [_scored("123", "RFA-1", close), _scored("nih-guide:9", "RFA-1", close)], 2) == ["nih-guide:9"]

def test_store_keeps_rows_without_a_number_or_a_deadline(tmp_path) -> None:
    store = OpportunityStore(tmp_path / "grants.sqlite3")
    try:
        for source_id in ("a", "b"):
            store.upsert_scored(MLRelevanceScorer().score(Opportunity(source_id=source_id, opportunity_number="", title="Machine learning", agency_code="HHS-NIH11", agency_name="National Institutes of Health", status="posted"), today=date(2026, 7, 6)))
        assert sorted(item.opportunity.source_id for item in store.top_scored(today=date(2026, 7, 6))) == ["a", "b"]
    finally:
        store.close()

def test_store_keeps_one_row_per_opportunity_number(tmp_path) -> None:
    close = date(2026, 12, 1)
    assert _saved_ids(tmp_path, [_scored("123", "RFA-1", close), _scored("nih-guide:9", "RFA-1", close), _scored("456", "RFA-1", close)], 2) == ["nih-guide:9"]

def test_a_read_scores_saved_rows_again(tmp_path) -> None:
    from dataclasses import replace
    from nih_grant_matcher.workflow import load_saved
    # No deadline, so the score does not depend on the day the test runs.
    opportunity = Opportunity(source_id="nih-guide:1", opportunity_number="RFA-ABC", title="Machine learning for health", agency_code="NIH", agency_name="National Institutes of Health", status="active", description="Machine learning and predictive models for health data.", raw={"docnum": "RFA-ABC"})
    fresh = MLRelevanceScorer().score(opportunity)
    store = OpportunityStore(tmp_path / "grants.sqlite3")
    try:
        store.upsert_scored(replace(fresh, score=1.0, classification="Watchlist"))
    finally:
        store.close()
    [loaded] = load_saved(str(tmp_path / "grants.sqlite3"))
    assert (loaded.score, loaded.classification) == (fresh.score, fresh.classification) != (1.0, "Watchlist")
    assert loaded.opportunity.raw == {"docnum": "RFA-ABC"}

def test_a_read_only_database_still_reads(tmp_path, capsys) -> None:
    from dataclasses import replace
    from nih_grant_matcher.workflow import load_saved
    path = tmp_path / "grants.sqlite3"
    store = OpportunityStore(path)
    try:
        store.upsert_scored(replace(MLRelevanceScorer().score(Opportunity(source_id="nih-guide:1", opportunity_number="RFA-ABC", title="Machine learning for health", agency_code="NIH", agency_name="National Institutes of Health", status="active")), score=1.0))
    finally:
        store.close()
    path.chmod(0o444)
    [loaded] = load_saved(str(path))
    assert loaded.score == 1.0
    assert "Could not update the saved scores" in capsys.readouterr().err
