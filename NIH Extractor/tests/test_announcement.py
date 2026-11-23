from datetime import datetime
from pathlib import Path
import pytest
from nih_grant_matcher import clients
from nih_grant_matcher.announcement import Announcement, fetch_announcement, html_to_text, parse_requirements, quoted_in
from nih_grant_matcher.models import Opportunity
from helpers import Grants, Guide

TEXT = (Path(__file__).parent / "fixtures" / "announcement_par.txt").read_text(encoding="utf-8")
OPP = Opportunity(source_id="nih-guide:9", opportunity_number="PAR-27-090", title="t", agency_code="NCI", agency_name="NIH NCI", status="active", funding_instruments=("R01",), raw={"guide_item": {"ggid": "360675"}})
SMALL = "Part 1. Overview Section I. Notice of Funding Opportunity DescriptionSection IV. Application and Submission InformationSection V. Application Review Information Part 2. Section I. Notice of Funding Opportunity Description Research areas include, but are not limited to: pain. Section III. Eligibility Information Eligible organizations are listed here. Section IV. Application and Submission Information See Section III. Eligibility Information for who may apply. PHS 398 Research PlanAll instructions in the How to Apply - Application Guide must be followed, with the following additional instructions: Research Strategy: Applicants must describe the data sharing approach. The Research Strategy is limited to 6 pages. PHS Human Subjects and Clinical Trials InformationAll instructions must be followed. Section V. Application Review Information Factor 1. Importance of the Research."

def _announcement(text: str) -> Announcement:
    return Announcement("PAR-27-090", text, "nih-guide", "u", "0" * 64, datetime(2026, 11, 23))

def test_the_guide_text_is_used_when_it_is_there() -> None:
    found = fetch_announcement(OPP, Guide(TEXT), Grants(""))
    assert found.origin == "nih-guide" and len(found.sha256) == 64

def test_the_real_announcement_splits_at_its_real_headings() -> None:
    real = _announcement(TEXT)
    assert real.section("IV").startswith("Section IV. Application and Submission Information 1. Requesting")
    assert "Rigor and Feasibility" in real.section("V") and "Rigor and Feasibility" not in real.section("IV")
    assert len(real.section("V")) == 10689 and real.section("IX") == ""

def test_a_heading_in_the_table_of_contents_or_in_a_sentence_is_not_a_section_start() -> None:
    small = _announcement(SMALL)
    assert small.section("I").startswith("Section I. Notice of Funding Opportunity Description Research areas")
    assert small.section("III") == "Section III. Eligibility Information Eligible organizations are listed here. "
    assert small.section("IV").startswith("Section IV. Application and Submission Information See Section III.") and "PHS 398 Research Plan" in small.section("IV")

def test_fetch_falls_back_to_the_grants_gov_attachment() -> None:
    found = fetch_announcement(OPP, Guide(""), Grants("<h2>Section IV. Application and Submission Information</h2><p>The Research Strategy is limited to 6&nbsp;pages.</p><script>x()</script>"))
    assert found.origin == "grants.gov" and "limited to 6 pages" in found.text and "x()" not in found.text

def test_no_source_is_an_error_that_names_both() -> None:
    with pytest.raises(clients.ApiError, match="NIH Guide.*Grants.gov"):
        fetch_announcement(OPP, Guide(""), Grants(""))

def test_a_page_limit_and_the_research_plan_instructions_are_read_with_their_quotes() -> None:
    found = parse_requirements(_announcement(SMALL))
    assert [(r.kind, r.section, r.limit.amount if r.limit else None, r.origin, r.confirmed) for r in found] == [("must", "research-strategy", None, "parsed", None), ("limit", "research-strategy", 6, "parsed", None)]
    assert found[0].quote.startswith("Research Strategy: Applicants must describe") and all(quoted_in(r.quote, SMALL) for r in found)

def test_not_limited_to_is_not_a_page_limit() -> None:
    assert [r for r in parse_requirements(_announcement(TEXT)) if r.kind == "limit"] == []
    assert all(quoted_in(r.quote, TEXT) for r in parse_requirements(_announcement(TEXT)))

def test_an_announcement_without_section_headings_yields_no_requirements() -> None:
    assert parse_requirements(_announcement("A notice of special interest with no numbered sections.")) == ()
