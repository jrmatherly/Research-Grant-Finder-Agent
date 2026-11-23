import json, pytest
from datetime import date
from nih_grant_matcher.config import MatcherConfig
from nih_grant_matcher.models import Opportunity
from nih_grant_matcher.profile import BUILTIN_PROFILE, EXPORT_FORMAT, Profile, ProfileError, from_export, suggest_terms, to_export
from nih_grant_matcher.scoring import MLRelevanceScorer
from nih_grant_matcher.store import OpportunityStore
from nih_grant_matcher.workflow import config_for

WET_LAB = Profile(keywords={"mitochondria": 18, "clinical trial": 10}, examples=("Study mitochondrial dynamics in cardiac muscle.",), focus="profile", examples_name="your example sentences")
OLD_SCHEMA = "CREATE TABLE opportunities (source_id TEXT PRIMARY KEY, opportunity_number TEXT, title TEXT NOT NULL, agency_code TEXT, agency_name TEXT, status TEXT, open_date TEXT, close_date TEXT, description TEXT, eligibility_json TEXT, funding_instruments_json TEXT, funding_categories_json TEXT, award_ceiling REAL, award_floor REAL, source_url TEXT, attachments_json TEXT, raw_json TEXT); CREATE TABLE scores (source_id TEXT PRIMARY KEY, score REAL NOT NULL, classification TEXT NOT NULL, reasons_json TEXT NOT NULL, matched_terms_json TEXT NOT NULL, breakdown_json TEXT NOT NULL, scored_at TEXT NOT NULL);"

def _nih(title: str, description: str) -> Opportunity:
    return Opportunity(source_id="nih-guide:1", opportunity_number="PA-1", title=title, agency_code="NHLBI", agency_name="NIH NHLBI", status="active", description=description)

def test_the_builtin_profile_gives_the_default_config() -> None:
    assert BUILTIN_PROFILE.matcher_config() == MatcherConfig()

def test_an_export_round_trips_and_has_only_profile_fields() -> None:
    data = json.loads(to_export(WET_LAB))
    assert data["format"] == EXPORT_FORMAT and from_export(to_export(WET_LAB)) == WET_LAB
    assert set(data["profile"]) == set(Profile.__dataclass_fields__)

@pytest.mark.parametrize("change, field", [({"format": "other/9"}, "format"), ({"profile": {"keywords": {"x": 99}}}, "keywords"), ({"profile": {"keywords": {"": 5}}}, "keywords"), ({"profile": {"api_key": "sk-1"}}, "api_key"), ({"profile": {"keywords": {str(n): 5 for n in range(201)}}}, "keywords"), ({"profile": {"keywords": {"Mitochondria": 5}}}, "keywords")])
def test_a_bad_import_is_refused_and_names_the_field(change, field) -> None:
    data = json.loads(to_export(BUILTIN_PROFILE))
    data = {**data, **{k: v for k, v in change.items() if k != "profile"}, "profile": {**data["profile"], **change.get("profile", {})}}
    with pytest.raises(ProfileError, match=field):
        from_export(json.dumps(data))

def test_a_custom_profile_drops_the_ai_rule_and_its_own_generic_terms() -> None:
    scored = MLRelevanceScorer(WET_LAB.matcher_config()).score(_nih("Mitochondria in an AI clinical trial", "A clinical trial of mitochondria for prevention and therapeutic use in community health."), today=date(2026, 7, 6))
    assert scored.matched_terms == ("mitochondria", "clinical trial")
    # Three generic terms remain once the profile's own "clinical trial" is left out: 3 * 2 - 2 matched terms. The code on main gives 5.0.
    assert scored.breakdown.generic_penalty == 4.0
    assert scored.reasons[0] == "Matched profile terms: mitochondria, clinical trial"

def test_the_store_returns_the_builtin_profile_until_one_is_saved(tmp_path) -> None:
    store = OpportunityStore(tmp_path / "g.sqlite3")
    try:
        assert store.profile() == BUILTIN_PROFILE and config_for(store) == MatcherConfig()
        store.save_profile(WET_LAB)
        assert store.profile() == WET_LAB and config_for(store).keywords == WET_LAB.keywords
        store.save_profile(None)
        assert store.profile() == BUILTIN_PROFILE
    finally:
        store.close()

def test_a_read_only_database_from_before_the_profile_still_opens(tmp_path) -> None:
    import sqlite3
    path = tmp_path / "old.sqlite3"
    sqlite3.connect(path).executescript(OLD_SCHEMA)
    path.chmod(0o444)
    try:
        store = OpportunityStore(path)
        assert store.profile() == BUILTIN_PROFILE and config_for(store) == MatcherConfig()
        store.close()
    finally:
        path.chmod(0o644)

def test_an_export_keeps_the_order_of_the_keywords() -> None:
    assert list(from_export(to_export(Profile(keywords={"zebrafish": 5, "aorta": 9}))).keywords) == ["zebrafish", "aorta"]

def test_suggested_terms_are_the_rarest_words_of_the_sentences() -> None:
    terms = suggest_terms(("Study mitochondrial dynamics in research.",), {"research": 900, "study": 800, "mitochondrial": 3, "dynamics": 40}, documents=1000)
    assert list(terms)[0] == "mitochondrial" and "research" not in terms and all(4 <= weight <= 18 for weight in terms.values())

def test_a_profile_that_would_not_load_is_not_saved(tmp_path) -> None:
    store = OpportunityStore(tmp_path / "g.sqlite3")
    try:
        store.save_profile(WET_LAB)
        with pytest.raises(ProfileError, match="keywords"):
            store.save_profile(Profile(keywords={"x": 99}))
        assert store.profile() == WET_LAB
    finally:
        store.close()
