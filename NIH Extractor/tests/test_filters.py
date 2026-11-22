from datetime import date
from nih_grant_matcher.filters import is_current_nih_hhs_opportunity
from nih_grant_matcher.models import Opportunity

def test_filter_rejects_expired_opportunity() -> None:
    opportunity = Opportunity(source_id="old", opportunity_number="OLD", title="Machine learning", agency_code="HHS-NIH11", agency_name="National Institutes of Health", status="posted", close_date=date(2026, 1, 1))
    assert not is_current_nih_hhs_opportunity(opportunity, today=date(2026, 7, 6))

def test_filter_accepts_current_nih_opportunity() -> None:
    opportunity = Opportunity(source_id="new", opportunity_number="NEW", title="Machine learning", agency_code="HHS-NIH11", agency_name="National Institutes of Health", status="forecasted", close_date=date(2026, 12, 1))
    assert is_current_nih_hhs_opportunity(opportunity, today=date(2026, 7, 6))

def test_filter_matches_agency_tokens_as_whole_words() -> None:
    def grant(code: str, name: str) -> Opportunity:
        return Opportunity(source_id="1", opportunity_number="X", title="Machine learning", agency_code=code, agency_name=name, status="posted")
    assert not is_current_nih_hhs_opportunity(grant("VA", "Commonwealth of Virginia"), today=date(2026, 7, 6))
    assert is_current_nih_hhs_opportunity(grant("HHS-NIH11", ""), today=date(2026, 7, 6))
    assert is_current_nih_hhs_opportunity(grant("", "National Institute on Aging (NIA)"), today=date(2026, 7, 6))
