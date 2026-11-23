from dataclasses import replace
from nih_grant_matcher.models import Opportunity
from nih_grant_matcher.rules import FACT_KINDS, GRANT_TYPES, Limit, grant_types_for, why_not_covered

def _opp(*codes: str) -> Opportunity:
    return Opportunity(source_id="nih-guide:1", opportunity_number="PAR-1", title="t", agency_code="NCI", agency_name="NIH NCI", status="active", funding_instruments=codes)

def test_research_strategy_follows_the_page_limit_table() -> None:
    limit = lambda code: next(s.limit for s in GRANT_TYPES[f"NIH:{code}"].sections if s.key == "research-strategy")
    assert {code: limit(code).amount for code in ("R01", "R15", "R34", "RF1", "U01", "R21", "R03", "R16")} == {"R01": 12, "R15": 12, "R34": 12, "RF1": 12, "U01": 12, "R21": 6, "R03": 6, "R16": 6}
    assert set(GRANT_TYPES) == {f"NIH:{code}" for code in ("R01", "R15", "R34", "RF1", "U01", "R21", "R03", "R16")}

def test_every_entry_names_its_sources_and_only_known_fact_kinds() -> None:
    for grant_type in GRANT_TYPES.values():
        assert grant_type.sources and all(source.url.startswith("https://grants.nih.gov/") and source.read_on for source in grant_type.sources)
        assert all(set(section.needs) | set(section.uses) <= set(FACT_KINDS) for section in grant_type.sections)
        assert all(section.model in ("none", "edit", "draft") for section in grant_type.sections)
        assert [factor.scale for factor in grant_type.factors] == ["1-9", "1-9", "appropriate"]

def test_an_opportunity_maps_to_the_covered_codes_it_lists() -> None:
    assert [g.code for g in grant_types_for(_opp("R21", "R01"))] == ["R21", "R01"]
    assert [g.code for g in grant_types_for(_opp("U01"))] == ["U01"]
    assert grant_types_for(_opp("R61", "R33")) == () and grant_types_for(_opp("UM1")) == () and grant_types_for(_opp()) == ()

def test_a_phased_award_or_a_non_nih_agency_gets_no_grant_type() -> None:
    assert grant_types_for(_opp("R21", "R33")) == () and grant_types_for(_opp("UG3", "UH3")) == ()
    assert [g.code for g in grant_types_for(replace(_opp("R01"), agency_code="NCI"))] == ["R01"]
    assert grant_types_for(replace(_opp("R01"), agency_code="FDA")) == () and grant_types_for(replace(_opp("R01"), agency_code="NIOSH")) == ()

def test_the_reason_a_listed_code_is_not_covered_is_said_in_a_sentence() -> None:
    assert "phased award" in why_not_covered(_opp("R21", "R33")) and "own criteria" in why_not_covered(replace(_opp("R01"), agency_code="FDA"))
    assert why_not_covered(_opp("R01")) == "" and why_not_covered(_opp("UM1")) == ""
