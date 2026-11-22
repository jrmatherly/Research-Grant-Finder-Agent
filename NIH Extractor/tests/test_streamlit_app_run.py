from datetime import date, timedelta
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from nih_grant_matcher.models import Opportunity
from nih_grant_matcher.scoring import MLRelevanceScorer
from nih_grant_matcher.store import OpportunityStore

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"


def test_dashboard_renders_saved_results(tmp_path, monkeypatch) -> None:
    opportunity = Opportunity(source_id="nih-guide:1", opportunity_number="RFA-TEST-1", title="Machine learning for health", agency_code="NLM", agency_name="NIH NLM", status="active", close_date=date.today() + timedelta(days=60), description="Machine learning for health data.")
    store = OpportunityStore(tmp_path / "data" / "grants.sqlite3")
    try:
        store.upsert_scored(MLRelevanceScorer().score(opportunity))
    finally:
        store.close()
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert not app.exception
    assert app.metric[0].value == "1"
