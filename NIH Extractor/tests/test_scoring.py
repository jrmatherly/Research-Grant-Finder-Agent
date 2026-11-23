from datetime import date
import pytest
from nih_grant_matcher.models import Opportunity
from nih_grant_matcher.scoring import MLRelevanceScorer

def test_ml_opportunity_scores_high() -> None:
    opportunity = Opportunity(source_id="1", opportunity_number="RFA-TEST-1", title="Deep learning for clinical prediction from EHR data", agency_code="HHS-NIH11", agency_name="National Institutes of Health", status="posted", close_date=date(2026, 12, 1), description="This NOFO supports machine learning and predictive modeling for patient outcomes.")
    scored = MLRelevanceScorer().score(opportunity, today=date(2026, 7, 6))
    assert scored.score >= 70
    assert scored.classification == "High"
    assert "machine learning" in scored.matched_terms

def test_generic_biomedical_opportunity_stays_low() -> None:
    opportunity = Opportunity(source_id="2", opportunity_number="PAR-TEST-2", title="Community health implementation research", agency_code="HHS-NIH11", agency_name="National Institutes of Health", status="posted", close_date=date(2026, 12, 1), description="Supports prevention, capacity building, health disparities, and clinical trial readiness.")
    scored = MLRelevanceScorer().score(opportunity, today=date(2026, 7, 6))
    assert scored.score < 45
    assert scored.classification == "Watchlist"

def _nih(title: str, description: str) -> Opportunity:
    return Opportunity(source_id="3", opportunity_number="PAR-TEST-3", title=title, agency_code="HHS-NIH11", agency_name="National Institutes of Health", status="posted", close_date=date(2026, 12, 1), description=description)

def test_keywords_match_whole_words_only() -> None:
    scored = MLRelevanceScorer().score(_nih("Health economics of cardiac remodeling", "Studies the economics of ventricular remodeling in aging adults."), today=date(2026, 7, 6))
    assert scored.matched_terms == ()
    assert scored.classification == "Watchlist"

def test_keywords_match_suffixes_and_omics_words() -> None:
    scored = MLRelevanceScorer().score(_nih("Algorithms for genomics", "Risk models built on multimodal datasets and EHRs. Ehrlichia is a bacterium."), today=date(2026, 7, 6))
    assert set(scored.matched_terms) == {"algorithm", "omics", "risk model", "multimodal data", "ehr"}
    assert scored.breakdown.keyword_score == 7 + 10 + 14 + 12 + 10

def test_overlapping_keywords_count_once() -> None:
    scored = MLRelevanceScorer().score(_nih("Predictive modeling of outcomes", "Predictive modeling."), today=date(2026, 7, 6))
    assert scored.matched_terms == ("predictive modeling",)
    assert scored.breakdown.keyword_score == 16

def test_title_credit_follows_the_overlap_rule() -> None:
    scored = MLRelevanceScorer().score(_nih("Predictive modeling of outcomes", "A separate modeling aim."), today=date(2026, 7, 6))
    assert scored.matched_terms == ("predictive modeling", "modeling")
    assert scored.breakdown.centrality_score == 12 + 1.5

def test_custom_keyword_with_symbols_matches() -> None:
    from nih_grant_matcher.config import MatcherConfig
    scored = MLRelevanceScorer(MatcherConfig(keywords={"c++": 5, ".net": 5})).score(_nih("Tools in C++ and .NET", "No other terms."), today=date(2026, 7, 6))
    assert scored.matched_terms == ("c++", ".net")

def test_common_words_do_not_count_as_similarity() -> None:
    scored = MLRelevanceScorer().score(_nih("Support for the care of patients", "Funds to support the use of tools to help patients and families from rural areas to get care and to learn from data."), today=date(2026, 7, 6))
    assert scored.breakdown.semantic_score < 8
    assert not any("curated" in reason for reason in scored.reasons)

def test_data_infrastructure_terms_match_under_readable_names() -> None:
    scored = MLRelevanceScorer().score(_nih("Statistical and Data Management Center", "Biostatistical support, data coordinating center duties, data harmonisation and secondary data analyses."), today=date(2026, 7, 6))
    assert set(scored.matched_terms) == {"statistical", "data management", "biostatistics", "data coordination", "data harmonization", "secondary analysis"}
    assert scored.breakdown.keyword_score == 8 + 8 + 12 + 10 + 10 + 10

@pytest.mark.parametrize("text, keyword, weight", [
    ("Medical imaging of tumors", "medical imaging", 12), ("Data integration across cohorts", "data integration", 10), ("Clinical informatics", "informatics", 12),
    ("Biostatistics core", "biostatistics", 12), ("Statistical methods and statistics", "statistical", 8), ("Quantitative approaches", "quantitative", 8),
    ("Data coordinating center", "data coordination", 10), ("Data management core", "data management", 8), ("Common data standards", "data standards", 10),
    ("Data harmonization", "data harmonization", 10), ("Secondary analysis of trials", "secondary analysis", 10), ("A shared data resource", "data resource", 8), ("Data sharing", "data sharing", 6),
])
def test_each_data_infrastructure_keyword_scores_its_weight(text: str, keyword: str, weight: int) -> None:
    scored = MLRelevanceScorer().score(_nih("Program", f"{text}."), today=date(2026, 7, 6))
    assert scored.matched_terms == (keyword,)
    assert scored.breakdown.keyword_score == weight

def test_application_boilerplate_is_not_a_keyword() -> None:
    scored = MLRelevanceScorer().score(_nih("Program", "Results were statistically significant. Applicants submit a Data Management and Sharing Plan. Ergonomics matters."), today=date(2026, 7, 6))
    assert scored.matched_terms == ()

def test_keywords_that_share_words_count_once() -> None:
    scorer = MLRelevanceScorer()
    assert scorer.score(_nih("Medical imaging analytics core", ""), today=date(2026, 7, 6)).matched_terms == ("imaging analytics",)
    assert scorer.score(_nih("Clinical prediction models", ""), today=date(2026, 7, 6)).matched_terms == ("clinical prediction",)
    both = scorer.score(_nih("Medical imaging analytics core", "A second aim uses medical imaging."), today=date(2026, 7, 6))
    assert set(both.matched_terms) == {"imaging analytics", "medical imaging"}

def test_a_title_alone_cannot_reach_the_similarity_reason() -> None:
    for title in ("Patient Outcomes", "Disease Mechanisms", "Biomedical imaging"):
        scored = MLRelevanceScorer().score(_nih(title, ""), today=date(2026, 7, 6))
        assert scored.breakdown.semantic_score < 8, title

def test_similarity_reason_lists_the_three_strongest_shared_terms() -> None:
    scored = MLRelevanceScorer().score(_nih("Program", "Extract phenotypes from clinical text with natural language processing. " * 3), today=date(2026, 7, 6))
    reason = next(reason for reason in scored.reasons if "curated" in reason)
    terms = reason.rsplit(": ", 1)[1].rstrip(")").split(", ")
    # The text shares seven words with the example. Three are named, and the common word "clinical" is not one of them.
    assert len(terms) == 3 and set(terms) <= {"natural", "language", "processing", "extract", "phenotypes", "text"}

def test_similarity_weights_rare_words_above_common_ones() -> None:
    scorer = MLRelevanceScorer()
    filler = "Supports investigators who study kidney stones, bladder function and urinary tract infection in older adults. Projects may enroll cohorts, collect specimens, measure symptoms and compare surgical, dietary and pharmacologic treatment across sites."
    rare = scorer.score(_nih("Urology", f"{filler} Phenotypes."), today=date(2026, 7, 6))
    common = scorer.score(_nih("Urology", f"{filler} Health."), today=date(2026, 7, 6))
    assert rare.breakdown.semantic_score > 2 * common.breakdown.semantic_score

def test_rarity_table_is_present_and_plausible() -> None:
    scorer = MLRelevanceScorer()
    assert scorer.documents >= 1000
    assert scorer.document_frequency["research"] > scorer.document_frequency["phenotypes"] > 1

def test_medium_starts_at_35_and_high_at_70() -> None:
    assert [MLRelevanceScorer._classification(score) for score in (34.9, 35, 69.9, 70)] == ["Watchlist", "Medium", "Medium", "High"]

def test_the_level_follows_the_score_that_is_shown(monkeypatch) -> None:
    # The parts add up to 69.96, which is shown as 70.0, so the level is High. The closed deadline takes 20 away.
    monkeypatch.setattr(MLRelevanceScorer, "_completeness_score", staticmethod(lambda opportunity: 89.96))
    scored = MLRelevanceScorer().score(Opportunity(source_id="1", opportunity_number="X", title="Notice", agency_code="", agency_name="", status="posted", close_date=date(2026, 1, 1)), today=date(2026, 7, 6))
    assert (scored.score, scored.classification) == (70.0, "High")


def test_ai_an_is_not_artificial_intelligence() -> None:
    scored = MLRelevanceScorer().score(_nih("Substance use prevention in AI/AN communities", "Community research with American Indian and Alaska Native (AI / ANs) youth."), today=date(2026, 7, 6))
    assert "AI" not in scored.matched_terms
    assert scored.classification == "Watchlist"

@pytest.mark.parametrize("title", ["AI tools for AI/AN health", "AI/ML methods for imaging", "PRIMED-AI coordination", "AI/Analytics core"])
def test_ai_matches_beside_ai_an(title: str) -> None:
    assert "AI" in MLRelevanceScorer().score(_nih(title, ""), today=date(2026, 7, 6)).matched_terms


def test_score_bin_edges_follow_the_levels() -> None:
    from nih_grant_matcher.scoring import score_bin
    assert [score_bin(score) for score in (0, 24.9, 25, 34.9, 35, 69.9, 70, 100)] == ["0-25", "0-25", "25-35", "25-35", "35-70", "35-70", "70-100", "70-100"]
    assert (MLRelevanceScorer._classification(35.0), MLRelevanceScorer._classification(70.0)) == ("Medium", "High")
