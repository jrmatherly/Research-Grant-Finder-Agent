from datetime import date
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

def test_similarity_weights_rare_words_above_common_ones() -> None:
    scorer = MLRelevanceScorer()
    filler = "Supports investigators who study kidney stones, bladder function and urinary tract infection in older adults."
    rare = scorer.score(_nih("Urology", f"{filler} Phenotypes."), today=date(2026, 7, 6))
    common = scorer.score(_nih("Urology", f"{filler} Health."), today=date(2026, 7, 6))
    assert rare.breakdown.semantic_score > 2 * common.breakdown.semantic_score
    assert rare.breakdown.semantic_score >= 8
    assert "Description is close to curated ML/data-science grant examples (shared terms: phenotypes)" in rare.reasons

def test_rarity_table_is_present_and_plausible() -> None:
    scorer = MLRelevanceScorer()
    assert scorer.documents >= 1000
    assert scorer.document_frequency["research"] > scorer.document_frequency["phenotypes"] > 1
