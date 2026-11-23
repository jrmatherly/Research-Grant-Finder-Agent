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

def _in_section_iv(sentence: str) -> str:
    return f"Section IV. Application and Submission Information Format the attachments. {sentence} Section V. Application Review Information Factor 1."

def test_every_limit_in_one_sentence_is_read_with_the_whole_sentence() -> None:
    sentence = "The Specific Aims is limited to 1 page and the Research Strategy is limited to 6 pages."
    found = parse_requirements(_announcement(_in_section_iv(sentence)))
    assert [(r.section, r.limit.amount if r.limit else None, r.quote) for r in found] == [("specific-aims", 1, sentence), ("research-strategy", 6, sentence)]

def test_a_decimal_point_does_not_end_the_quoted_sentence() -> None:
    sentence = "For version 2.0 forms, the Research Strategy is limited to 12 pages."
    assert [r.quote for r in parse_requirements(_announcement(_in_section_iv(sentence)))] == [sentence]

def test_a_guide_reply_with_a_malformed_hit_falls_back_to_grants_gov(monkeypatch) -> None:
    monkeypatch.setattr(clients, "_read", lambda request, timeout, attempts=3: b'{"data": {"hits": {"hits": [{"_source": "PAR-27-090"}]}}}')
    found = fetch_announcement(OPP, clients.NihGuideClient(), Grants("<p>Section IV. Application and Submission Information</p>"))
    assert found.origin == "grants.gov"

def test_a_grants_gov_id_that_is_not_a_number_ends_in_the_error_that_names_both(monkeypatch) -> None:
    def no_network(request, timeout, attempts=3): raise AssertionError("no request may be sent")
    monkeypatch.setattr(clients, "_read", no_network)
    opportunity = Opportunity(source_id="nih-guide:9", opportunity_number="PAR-27-090", title="t", agency_code="NCI", agency_name="NIH NCI", status="active", raw={"guide_item": {"ggid": "../x"}})
    with pytest.raises(clients.ApiError, match="NIH Guide.*Grants.gov.*not a number"):
        fetch_announcement(opportunity, Guide(""), clients.GrantsGovClient())
