from datetime import date, timedelta
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from nih_grant_matcher.models import Opportunity
from nih_grant_matcher.scoring import MLRelevanceScorer
from nih_grant_matcher.store import OpportunityStore

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"


# The dashboard reads the real date, so the deadlines here are set relative to today instead of fixed.
def test_dashboard_renders_saved_open_results(tmp_path, monkeypatch) -> None:
    opportunity = Opportunity(source_id="nih-guide:1", opportunity_number="RFA-TEST-1", title="Machine learning for health", agency_code="NLM", agency_name="NIH NLM", status="active", close_date=date.today() + timedelta(days=60), description="Machine learning for health data.")
    closed = Opportunity(source_id="nih-guide:2", opportunity_number="RFA-TEST-2", title="Machine learning, closed", agency_code="NLM", agency_name="NIH NLM", status="active", close_date=date.today() - timedelta(days=1))
    store = OpportunityStore(tmp_path / "data" / "grants.sqlite3")
    try:
        store.upsert_scored(MLRelevanceScorer().score(opportunity))
        store.upsert_scored(MLRelevanceScorer().score(closed))
    finally:
        store.close()
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert not app.exception
    assert app.metric[0].value == "1"
    labels = [metric.label for metric in app.metric]
    assert labels[:4] == ["Visible Opportunities", "High Matches", "Median Score", "Next Expiration"]
    assert "Expires" in labels and not any("Deadline" in label for label in labels)
    assert "Expirations by Month" in [subheader.value for subheader in app.subheader]
    assert "Close Month" not in app.dataframe[0].value.columns
    assert any("Expires is the day the notice expires" in caption.value for caption in app.caption)


def test_dashboard_says_when_it_shows_scores_as_last_saved(tmp_path, monkeypatch) -> None:
    import os
    path = tmp_path / "data" / "grants.sqlite3"
    store = OpportunityStore(path)
    try:
        store.upsert_scored(MLRelevanceScorer().score(Opportunity(source_id="nih-guide:1", opportunity_number="RFA-TEST-1", title="Machine learning for health", agency_code="NLM", agency_name="NIH NLM", status="active")))
    finally:
        store.close()
    path.chmod(0o444)
    if getattr(os, "geteuid", lambda: 1)() == 0:
        pytest.skip("root writes to a read-only file")
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert not app.exception
    assert app.metric[0].value == "1"
    assert any("shown as last saved" in warning.value for warning in app.warning)


def test_the_profile_view_is_reachable_with_an_empty_database(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    assert not app.exception
    assert any("built-in profile" in info.value for info in app.info)
    assert "Set up my profile" in [button.label for button in app.button]


def test_importing_a_profile_saves_it(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.profile import Profile, to_export
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    app.text_area(key="profile_import_text").set_value(to_export(Profile(keywords={"mitochondria": 18}, examples=("Study mitochondria.",)))).run(timeout=30)
    app.button(key="profile_import_save").click().run(timeout=30)
    store = OpportunityStore(tmp_path / "data" / "grants.sqlite3")
    try:
        assert store.profile().keywords == {"mitochondria": 18}
    finally:
        store.close()


def test_saving_a_profile_reorders_the_find_view(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.profile import Profile, to_export
    def opp(n, title):
        return Opportunity(source_id=f"nih-guide:{n}", opportunity_number=f"PA-{n}", title=title, agency_code="NHLBI", agency_name="NIH NHLBI", status="active", close_date=date.today() + timedelta(days=60), description=title)
    store = OpportunityStore(tmp_path / "data" / "grants.sqlite3")
    try:
        store.upsert_many([MLRelevanceScorer().score(opp(1, "Machine learning for imaging")), MLRelevanceScorer().score(opp(2, "Mitochondria in cardiac muscle"))])
    finally:
        store.close()
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert app.dataframe[0].value["Opportunity Number"].iloc[0] == "PA-1"
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    app.text_area(key="profile_import_text").set_value(to_export(Profile(keywords={"mitochondria": 18}, examples=("Study mitochondria in cardiac muscle.",), focus="profile", examples_name="your example sentences"))).run(timeout=30)
    app.button(key="profile_import_save").click().run(timeout=30)
    app.sidebar.radio[0].set_value("Find").run(timeout=30)
    assert app.dataframe[0].value["Opportunity Number"].iloc[0] == "PA-2"
