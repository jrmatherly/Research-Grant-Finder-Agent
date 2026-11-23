import json
from datetime import date
from pathlib import Path
from dataclasses import asdict
from nih_grant_matcher.models import Opportunity
from nih_grant_matcher.scoring import MLRelevanceScorer

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 23)

def load_golden() -> list[tuple[Opportunity, dict]]:
    def build(row: dict) -> Opportunity:
        row = dict(row, **{k: date.fromisoformat(row[k]) for k in ("open_date", "close_date") if row[k]})
        return Opportunity(**{k: tuple(v) if isinstance(v, list) else v for k, v in row.items()})
    opportunities = [build(row) for row in json.loads((FIXTURES / "golden_opportunities.json").read_text(encoding="utf-8"))]
    return list(zip(opportunities, json.loads((FIXTURES / "golden_scores.json").read_text(encoding="utf-8"))))

def as_golden(scored) -> dict:
    return {"source_id": scored.opportunity.source_id, "score": scored.score, "classification": scored.classification, "reasons": list(scored.reasons), "matched_terms": list(scored.matched_terms), "breakdown": asdict(scored.breakdown)}

def test_builtin_scores_match_the_frozen_file() -> None:
    scorer = MLRelevanceScorer()
    for opportunity, expected in load_golden():
        assert as_golden(scorer.score(opportunity, today=TODAY)) == expected

def test_the_fixture_exercises_every_rule_the_profile_work_touches() -> None:
    expected = [row for _, row in load_golden()]
    assert {row["classification"] for row in expected} == {"High", "Medium", "Watchlist"}
    assert any("AI" in row["matched_terms"] for row in expected) and any(row["breakdown"]["generic_penalty"] > 0 for row in expected)
    assert any("curated ML/data-science grant examples" in reason for row in expected for reason in row["reasons"])

def test_the_fallback_reason_keeps_its_wording() -> None:
    plain = Opportunity(source_id="x:1", opportunity_number="X-1", title="Road repair", agency_code="DOT", agency_name="Department of Transportation", status="posted")
    assert MLRelevanceScorer().score(plain, today=TODAY).reasons == ("Weak computational signal; included for monitoring only",)
