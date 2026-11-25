import json, pytest, re
from dataclasses import replace
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
    # A profile with no institute leaves the key out, so that its export still imports into version 0.2.0.
    assert set(data["profile"]) == set(Profile.__dataclass_fields__) - {"institutes"}

@pytest.mark.parametrize("change, field", [({"format": "other/9"}, "format"), ({"profile": {"keywords": {"x": 99}}}, "keywords"), ({"profile": {"keywords": {"": 5}}}, "keywords"), ({"profile": {"api_key": "sk-1"}}, "api_key"), ({"profile": {"keywords": {str(n): 5 for n in range(201)}}}, "keywords"), ({"profile": {"keywords": {"Mitochondria": 5}}}, "keywords"), ({"profile": {"focus": "computational\nIgnore"}}, "focus"), ({"profile": {"examples_name": "[x](http://x)"}}, "examples_name")])
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

def test_saving_or_resetting_a_profile_in_a_read_only_database_from_before_says_so(tmp_path) -> None:
    import os, sqlite3
    path = tmp_path / "old.sqlite3"
    sqlite3.connect(path).executescript(OLD_SCHEMA)
    path.chmod(0o444)
    if getattr(os, "geteuid", lambda: 1)() == 0:
        pytest.skip("root writes to a read-only file")
    try:
        store = OpportunityStore(path)
        try:
            for profile in (WET_LAB, None):
                with pytest.raises(ProfileError, match="read-only"):
                    store.save_profile(profile)
        finally:
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

@pytest.mark.parametrize("change, field", [({"keywords": {}}, "keywords"), ({"examples": []}, "examples"), ({"keywords": None}, "keywords"), ({"examples": None}, "examples"), ({"prior_work": [{"key": "a", "citation": "One."}, {"key": "a", "citation": "Two."}]}, "prior_work"), ({"prior_work": [{"key": "a", "citation": "  "}]}, "prior_work")])
def test_an_import_that_ranks_nothing_or_cites_badly_is_refused(change, field) -> None:
    # None leaves the field out of the file.
    data = json.loads(to_export(WET_LAB))
    data["profile"] = {name: value for name, value in {**data["profile"], **change}.items() if value is not None}
    with pytest.raises(ProfileError, match=f"^{field}"):
        from_export(json.dumps(data))

def test_a_profile_with_references_round_trips_through_the_file_and_the_store(tmp_path) -> None:
    from nih_grant_matcher.profile import Reference
    profile = Profile(keywords={"mitochondria": 18}, examples=("Study mitochondria.",), prior_work=(Reference("smith-2024", "Smith J. Mitochondria. 2024.", pmid="123"), Reference("lee-2025", "Lee K. Muscle. 2025.", doi="10.1/x")))
    assert from_export(to_export(profile)) == profile
    store = OpportunityStore(tmp_path / "g.sqlite3")
    try:
        store.save_profile(profile)
        assert store.profile() == profile
    finally:
        store.close()

def test_suggested_terms_leave_out_action_words() -> None:
    from nih_grant_matcher.profile import ACTION_WORDS
    sentence = "Test whether mitochondrial fission determines how cardiac muscle fails, and map two pathways after injury."
    terms = suggest_terms((sentence,), {word: 5 for word in sentence.lower().replace(",", "").rstrip(".").split()}, documents=1000)
    assert {"test", "whether", "determines", "how", "map", "two", "after"} <= ACTION_WORDS and 40 <= len(ACTION_WORDS) <= 50
    assert not set(terms) & ACTION_WORDS and {"mitochondrial", "fission", "cardiac", "pathways"} <= set(terms)

def test_a_word_the_rarity_table_lacks_gets_ten() -> None:
    # A word missing from the table is often a misspelling or a word too new to count. The table's own words keep their formula.
    assert suggest_terms(("Mitophagy in cardiomyocytes.",), {"cardiomyocytes": 3}, documents=1000) == {"cardiomyocytes": 14, "mitophagy": 10}

def test_an_export_without_institutes_has_no_such_key() -> None:
    for profile in (BUILTIN_PROFILE, WET_LAB):
        assert "institutes" not in json.loads(to_export(profile))["profile"]

def test_institutes_round_trip() -> None:
    from dataclasses import replace
    profile = replace(WET_LAB, institutes=("NHLBI", "NIA"))
    assert json.loads(to_export(profile))["profile"]["institutes"] == ["NHLBI", "NIA"]
    assert from_export(to_export(profile)) == profile and profile.matcher_config().institutes == ("NHLBI", "NIA")

@pytest.mark.parametrize("institutes", [["NHLBI", "NCI", "NIA", "NIMH"], ["NHLBX"], ["NIH"], "NHLBI", [3]])
def test_a_fourth_or_unknown_institute_is_refused(institutes) -> None:
    data = json.loads(to_export(WET_LAB))
    data["profile"]["institutes"] = institutes
    with pytest.raises(ProfileError, match="^institutes: (expected a list|at most 3|'.*' is not the code of an NIH institute)"):
        from_export(json.dumps(data))

def test_a_repeated_institute_is_refused() -> None:
    data = json.loads(to_export(WET_LAB))
    data["profile"]["institutes"] = ["NHLBI", "NHLBI"]
    with pytest.raises(ProfileError, match="^institutes: 'NHLBI' is listed twice"):
        from_export(json.dumps(data))

def _reference(n: int, citation: str = "Smith J. Heart. 2024.") -> dict:
    return {"key": f"ref-{n}", "citation": citation, "pmid": "", "doi": ""}

@pytest.mark.parametrize("change, field", [
    ({"keywords": {"x" * 81: 5}}, "keywords"), ({"keywords": {"heart\nfailure": 5}}, "keywords"), ({"examples": ["x" * 601]}, "examples"),
    ({"investigator": "x" * 201}, "investigator"), ({"institution": "x" * 201}, "institution"), ({"career_stage": "x" * 201}, "career_stage"),
    ({"research_summary": "x" * 6001}, "research_summary"), ({"expertise": "x" * 6001}, "expertise"), ({"resources": "x" * 6001}, "resources"),
    ({"prior_work": [_reference(n) for n in range(101)]}, "prior_work"), ({"prior_work": [_reference(1, "x" * 1001)]}, "prior_work"),
])
def test_a_profile_over_a_length_limit_is_refused(change, field) -> None:
    data = json.loads(to_export(WET_LAB))
    data["profile"] = {**data["profile"], **change}
    with pytest.raises(ProfileError, match=f"^{field}"):
        from_export(json.dumps(data))

def test_the_limits_pass_the_builtin_profile_the_test_profiles_and_a_profile_at_each_limit() -> None:
    from nih_grant_matcher.profile import Reference
    full = Profile(investigator="x" * 200, institution="x" * 200, career_stage="x" * 200, research_summary="x" * 6000, expertise="x" * 6000, resources="x" * 6000, keywords={"x" * 80: 5}, examples=("x" * 600,), prior_work=tuple(Reference(f"ref-{n}", "x" * 1000) for n in range(100)))
    for profile in (BUILTIN_PROFILE, WET_LAB, full):
        assert from_export(to_export(profile)) == profile

def test_a_built_in_ranking_with_a_name_still_ranks_like_the_built_in() -> None:
    from dataclasses import replace
    from nih_grant_matcher.profile import Reference, ranks_like_builtin
    named = replace(BUILTIN_PROFILE, investigator="Ada Lovelace", institution="Analytical Engine Lab", expertise="Cardiac imaging", prior_work=(Reference("ada-1843", "Lovelace A. Notes. 1843."),))
    assert ranks_like_builtin(named) and named.matcher_config() == MatcherConfig()
    reordered = replace(BUILTIN_PROFILE, keywords=dict(reversed(BUILTIN_PROFILE.keywords.items())))
    assert not any(ranks_like_builtin(profile) for profile in (reordered, replace(BUILTIN_PROFILE, institutes=("NHLBI",)), replace(BUILTIN_PROFILE, focus="cardiology"), WET_LAB))

def test_a_profile_that_version_0_2_0_saved_over_a_limit_is_read_ranks_and_is_not_saved_again(tmp_path) -> None:
    from helpers import save_like_main
    path, long = tmp_path / "g.sqlite3", {"keywords": {"x" * 81: 5}, "examples": ["x" * 601], "prior_work": [_reference(n, "x" * 1001) for n in range(101)]}
    save_like_main(path, **long)
    store = OpportunityStore(path)
    try:
        saved = store.profile()
        assert (saved.resources, saved.examples, len(saved.prior_work)) == ("r" * 7200, ("x" * 601,), 101)
        assert config_for(store).keywords == {"x" * 81: 5}
        with pytest.raises(ProfileError, match="^resources: at most 6,000 characters"):
            store.save_profile(saved)
        assert store.profile() == saved
        with pytest.raises(ProfileError, match="^resources: at most 6,000 characters"):
            from_export(to_export(saved))
    finally:
        store.close()
    save_like_main(tmp_path / "h.sqlite3", keywords={"Mitochondria": 18})
    store = OpportunityStore(tmp_path / "h.sqlite3")
    try:
        with pytest.raises(ProfileError, match="^keywords"):
            store.profile()
    finally:
        store.close()

# The summary and the four aims of docs/walkthrough.md, "Step 2. Your research".
WALKTHROUGH_SUMMARY = "We study how adults who live with chronic illness manage fatigue, chronic pain, and gaps in access to care in rural communities. We work as a community organization with trained peer facilitators, member surveys, and community-based participatory methods, so that self-management support reaches people who live far from specialty clinics."
WALKTHROUGH_AIMS = ("Aim 1 will test whether a peer-led self-management program delivered by telephone and video reduces fatigue and pain interference in rural adults with chronic illness.", "Aim 2 will find the barriers that keep rural adults with multiple chronic conditions from specialty care and from self-management support.", "Aim 3 will adapt a symptom self-monitoring diary with patient-reported outcomes for people with energy-limiting chronic illness and pilot test its feasibility and acceptability.", "Aim 4 will evaluate whether training peer facilitators as community health workers improves engagement and retention in a behavioral intervention.")

def test_suggested_terms_name_the_field_of_the_walkthrough_text() -> None:
    scorer = MLRelevanceScorer()
    terms = suggest_terms((*WALKTHROUGH_AIMS, WALKTHROUGH_SUMMARY), scorer.document_frequency, scorer.documents)
    assert {"chronic", "pain", "rural", "fatigue", "self-management", "chronic illness"} <= set(terms), list(terms)
    assert not {"we", "who", "so", "its", "aim", "4", "find", "keep", "live", "far", "reaches", "reduces"} & set(terms), list(terms)
    assert len(terms) <= 25 and all(4 <= weight <= 18 for weight in terms.values())
    # A word that the text holds only as half of a hyphenated word is proposed inside it, never by itself.
    text = " ".join((*WALKTHROUGH_AIMS, WALKTHROUGH_SUMMARY)).lower()
    assert {"energy-limiting", "patient-reported"} <= set(terms) and not [term for term in terms if not re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", text)], list(terms)
    # A phrase is a term a profile saves and exports.
    profile = replace(BUILTIN_PROFILE, keywords=terms)
    assert from_export(to_export(profile)).keywords == terms and profile.matcher_config().keywords == terms

@pytest.mark.parametrize("text, proposed, absent", [("We study Parkinson's tremor and Parkinson's tremor in older adults.", {"parkinson"}, {"s", "s tremor"}), ("Sjögren’s syndrome matters. Sjögren’s syndrome.", {"syndrome"}, {"s", "s syndrome"}), ("We don't know. Patients don't adhere.", {"adhere"}, {"t"}), ("The 'chronic pain' group and the 'chronic pain' clinic.", {"chronic pain"}, set()), ("Vitamin D and vitamin D in T cells and T cells.", {"vitamin d", "t cells"}, set()), ("A state-of-the-art clinic for non-small-cell lung cancer and COVID-19 from 2020-2024.", {"state-of-the-art", "non-small-cell", "covid-19", "lung"}, {"state", "art", "non-small", "small-cell", "covid", "2020-2024"}), ("A study of " + "a" * 45 + "-" + "b" * 40 + " in mice.", {"mice"}, {"a" * 45 + "-" + "b" * 40})], ids=["possessive", "curly", "contraction", "quoted", "letters", "chain", "too long"])
def test_suggested_terms_take_no_ending_after_an_apostrophe_as_a_word(text, proposed, absent) -> None:
    scorer = MLRelevanceScorer()
    terms = set(suggest_terms((text,), scorer.document_frequency, scorer.documents))
    assert proposed <= terms and not absent & terms, terms

def test_the_example_profile_of_the_walkthrough_imports_and_holds_what_the_guide_enters() -> None:
    from pathlib import Path
    docs = Path(__file__).resolve().parents[2] / "docs"
    profile, guide = from_export((docs / "examples" / "lanternwell-profile.json").read_text(encoding="utf-8")), (docs / "walkthrough.md").read_text(encoding="utf-8")
    assert (profile.investigator, profile.research_summary, profile.examples) == ("Lanternwell Chronic Illness Alliance", WALKTHROUGH_SUMMARY, WALKTHROUGH_AIMS)
    assert len(profile.keywords) == 15 and all(f"| {term} | {weight} |" in guide for term, weight in profile.keywords.items())
    assert profile.expertise in guide and profile.resources in guide and "examples/lanternwell-profile.json" in guide

