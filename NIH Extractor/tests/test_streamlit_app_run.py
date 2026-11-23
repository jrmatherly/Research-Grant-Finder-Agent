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
    assert app.caption[0].value == "Run NIH Guide and Grants.gov searches, rank computational opportunities, and explore the results interactively."
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    app.text_area(key="profile_import_text").set_value(to_export(Profile(keywords={"mitochondria": 18}, examples=("Study mitochondria in cardiac muscle.",), focus="profile", examples_name="your example sentences"))).run(timeout=30)
    app.button(key="profile_import_save").click().run(timeout=30)
    app.sidebar.radio[0].set_value("Find").run(timeout=30)
    assert app.dataframe[0].value["Opportunity Number"].iloc[0] == "PA-2"
    assert app.caption[0].value == "Run NIH Guide and Grants.gov searches, rank opportunities, and explore the results interactively."
    assert "Ranking uses the profile of an unnamed investigator, with 1 terms and 1 example sentences." in [caption.value for caption in app.caption]


def test_the_wizard_saves_every_step_and_resets(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.profile import BUILTIN_PROFILE
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    def press(label):
        next(button for button in app.button if button.label == label).click().run(timeout=30)
    press("Set up my profile")
    app.text_input[0].set_value("Ada Lovelace")
    press("Next")
    app.text_area[0].set_value("Mitochondria in the heart.")
    app.text_area[1].set_value("Measure mitochondrial fission in heart failure. Map cardiac muscle energetics. Test mitophagy in cardiomyocytes.")
    press("Next")
    press("Next")
    press("Next")
    app.text_area[0].set_value("Cardiac imaging")
    press("Save profile")
    assert not app.exception
    store = OpportunityStore(tmp_path / "data" / "grants.sqlite3")
    try:
        profile = store.profile()
        assert len(profile.examples) == 3 and profile.expertise == "Cardiac imaging" and profile.keywords
        assert (profile.investigator, profile.research_summary, profile.focus) == ("Ada Lovelace", "Mitochondria in the heart.", "profile")
        assert all(term == term.strip().lower() for term in profile.keywords)
    finally:
        store.close()
    press("Reset to built-in")
    store = OpportunityStore(tmp_path / "data" / "grants.sqlite3")
    try:
        assert store.profile() == BUILTIN_PROFILE
    finally:
        store.close()


def test_saving_on_the_first_step_saves_nothing(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.profile import BUILTIN_PROFILE
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    next(button for button in app.button if button.label == "Set up my profile").click().run(timeout=30)
    app.text_input[0].set_value("Ada Lovelace")
    next(button for button in app.button if button.label == "Save profile").click().run(timeout=30)
    assert not app.exception
    assert any("example sentences under step 2" in error.value for error in app.error)
    # A Save on step 2 does not merge in suggested terms that the user has not seen under step 3.
    next(button for button in app.button if button.label == "Next").click().run(timeout=30)
    app.text_area[0].set_value("Mitochondria in the heart.")
    app.text_area[1].set_value("Measure mitochondrial fission in heart failure. Map cardiac muscle energetics. Test mitophagy in cardiomyocytes.")
    next(button for button in app.button if button.label == "Save profile").click().run(timeout=30)
    assert not app.exception
    assert any("terms under step 3" in error.value for error in app.error)
    store = OpportunityStore(tmp_path / "data" / "grants.sqlite3")
    try:
        assert store.profile() == BUILTIN_PROFILE
    finally:
        store.close()


def test_an_unreadable_profile_ranks_with_the_builtin_one_and_can_be_reset(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.profile import BUILTIN_PROFILE
    path = tmp_path / "data" / "grants.sqlite3"
    store = OpportunityStore(path)
    try:
        store.upsert_scored(MLRelevanceScorer().score(Opportunity(source_id="nih-guide:1", opportunity_number="RFA-TEST-1", title="Machine learning for health", agency_code="NLM", agency_name="NIH NLM", status="active", close_date=date.today() + timedelta(days=60))))
        with store.conn:
            store.conn.execute("INSERT INTO profile VALUES (1, ?, ?)", ('{"format": "grant-matcher-profile/2", "profile": {}}', "2026-11-23T00:00:00"))
    finally:
        store.close()
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert not app.exception
    assert any("grant-matcher-profile/1" in error.value.replace("\\", "") for error in app.error)
    assert app.dataframe[0].value["Opportunity Number"].iloc[0] == "RFA-TEST-1"
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    assert not app.exception
    banner = next(error.value.replace("\\", "") for error in app.error if "grant-matcher-profile/1" in error.value.replace("\\", ""))
    assert "Reset to built-in under Profile deletes the saved profile" in banner and "only copy" in banner
    assert app.get("download_button")[0].disabled
    next(button for button in app.button if button.label == "Reset to built-in").click().run(timeout=30)
    assert not app.exception
    store = OpportunityStore(path)
    try:
        assert store.profile() == BUILTIN_PROFILE
    finally:
        store.close()


def _opp(n, title):
    return Opportunity(source_id=f"nih-guide:{n}", opportunity_number=f"PA-{n}", title=title, agency_code="NHLBI", agency_name="NIH NHLBI", status="active", close_date=date.today() + timedelta(days=60), description=title)


def _press(app, label):
    next(button for button in app.button if button.label == label).click().run(timeout=30)


def test_a_saved_profile_with_the_builtin_keywords_reordered_is_not_the_builtin_one(tmp_path) -> None:
    from nih_grant_matcher.profile import BUILTIN_PROFILE, Profile
    from nih_grant_matcher.ui.profile_page import saved_profile
    reordered, path = Profile(keywords=dict(reversed(BUILTIN_PROFILE.keywords.items()))), tmp_path / "g.sqlite3"
    store = OpportunityStore(path)
    try:
        store.save_profile(reordered)
    finally:
        store.close()
    saved = saved_profile(str(path))
    assert saved is not None and list(saved.keywords) == list(reordered.keywords)


def test_the_preview_shows_what_the_draft_raises_and_lowers(tmp_path, monkeypatch) -> None:
    store = OpportunityStore(tmp_path / "data" / "grants.sqlite3")
    try:
        store.upsert_many([MLRelevanceScorer().score(_opp(1, "Machine learning for imaging")), MLRelevanceScorer().score(_opp(2, "Mitochondria in cardiac muscle"))])
    finally:
        store.close()
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    _press(app, "Set up my profile")
    _press(app, "Next")
    app.text_area[0].set_value("Mitochondria in cardiac muscle.")
    app.text_area[1].set_value("Measure mitochondria in cardiac muscle. Map cardiac muscle energetics. Test mitochondria in cardiomyocytes.")
    _press(app, "Next")
    _press(app, "Next")
    assert not app.exception
    preview = app.dataframe[0].value.set_index("Opportunity Number")
    assert preview.loc["PA-2", "Change"] > 0 and preview.loc["PA-1", "Change"] < 0


def test_editing_an_imported_profile_keeps_its_focus(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.profile import Profile, to_export
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    app.text_area(key="profile_import_text").set_value(to_export(Profile(keywords={"tumor imaging": 12}, examples=("Image tumors.", "Grade tumors.", "Track tumors."), focus="oncology imaging"))).run(timeout=30)
    app.button(key="profile_import_save").click().run(timeout=30)
    _press(app, "Edit my profile")
    for _ in range(4):
        _press(app, "Next")
    _press(app, "Save profile")
    assert not app.exception
    store = OpportunityStore(tmp_path / "data" / "grants.sqlite3")
    try:
        assert store.profile().focus == "oncology imaging"
    finally:
        store.close()


def test_a_pasted_profile_cannot_put_a_link_in_the_page(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.profile import Profile, to_export
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    app.text_area(key="profile_import_text").set_value(to_export(Profile(investigator="[Click to verify](https://example.invalid)"))).run(timeout=30)
    captions = [caption.value for caption in app.caption]
    assert any("\\[Click to verify\\]\\(https" in caption for caption in captions)
    assert not any("[Click to verify](" in caption for caption in captions)


@pytest.mark.parametrize("make", [lambda path: path.write_text("not a database", encoding="utf-8"), lambda path: path.mkdir()])
def test_a_database_path_that_is_not_a_database_gives_a_message(tmp_path, monkeypatch, make) -> None:
    make(tmp_path / "notes.txt")
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.text_input[0].set_value("notes.txt").run(timeout=30)
    assert not app.exception
    assert app.warning
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    assert not app.exception
    assert app.error


def _r21_database(tmp_path, start=False):
    from helpers import opportunity
    from nih_grant_matcher.writer import Workspace
    store = OpportunityStore(tmp_path / "data" / "grants.sqlite3")
    try:
        saved = replace_close(opportunity())
        store.upsert_scored(MLRelevanceScorer().score(saved))
        if start:
            Workspace.start(store, saved, "NIH:R21")
    finally:
        store.close()
    return tmp_path / "data" / "grants.sqlite3"


def replace_close(opportunity):
    from dataclasses import replace
    return replace(opportunity, close_date=date.today() + timedelta(days=60))


def _apply_view(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Apply").run(timeout=30)
    return app


def test_start_application_opens_the_apply_view(tmp_path, monkeypatch) -> None:
    _r21_database(tmp_path)
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.button(key="start_application").click().run(timeout=30)
    assert not app.exception
    assert app.session_state["view"] == "Apply"
    page = " ".join(element.value for element in [*app.markdown, *app.caption])
    assert all(title in page for title in ("Specific Aims", "Research Strategy", "Project Summary/Abstract", "Project Narrative"))


def test_the_apply_view_says_how_to_start_an_application(tmp_path, monkeypatch) -> None:
    app = _apply_view(tmp_path, monkeypatch)
    assert not app.exception
    assert any("choose Start application" in info.value for info in app.info)
    _r21_database(tmp_path)
    app.run(timeout=30)
    assert not app.exception and any("choose Start application" in info.value for info in app.info)


def test_signing_an_over_limit_narrative_is_refused(tmp_path, monkeypatch) -> None:
    path = _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.selectbox(key="apply_section").set_value("project-narrative").run(timeout=30)
    app.text_area(key="apply_text_1_project-narrative").set_value("One. Two. Three. Four.")
    app.button(key="apply_save_button").click().run(timeout=30)
    assert not app.exception and any("Saved revision 1" in success.value for success in app.success)
    app.text_input(key="apply_signer").set_value("A. Applicant")
    app.button(key="apply_sign_button").click().run(timeout=30)
    assert not app.exception
    assert any("4 sentences" in error.value for error in app.error)
    store = OpportunityStore(path)
    try:
        assert store.signoffs(1) == [] and [r.text for r in store.revisions(1)] == ["One. Two. Three. Four."]
    finally:
        store.close()


def test_a_database_error_on_save_is_a_message(tmp_path, monkeypatch) -> None:
    import os
    path = _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    path.chmod(0o444)
    if getattr(os, "geteuid", lambda: 1)() == 0:
        pytest.skip("root writes to a read-only file")
    try:
        app.text_area(key="apply_text_1_specific-aims").set_value("Aim 1.")
        app.button(key="apply_save_button").click().run(timeout=30)
    finally:
        path.chmod(0o644)
    assert not app.exception
    assert any("readonly" in error.value.replace("\\", "") for error in app.error)


def _tabs_index(app):
    return next(index for index, child in app.main.children.items() if type(child).__name__ == "Block" and any(type(c).__name__ == "Tab" for c in child.children.values()))


def test_a_notice_does_not_move_the_tabs_or_change_the_open_tab(tmp_path, monkeypatch) -> None:
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    before = _tabs_index(app)
    app.session_state["apply_tab"] = "Sections"
    app.text_area(key="apply_text_1_specific-aims").set_value("Aim 1.")
    app.button(key="apply_save_button").click().run(timeout=30)
    assert not app.exception and app.success
    assert _tabs_index(app) == before and app.session_state["apply_tab"] == "Sections"
    app.run(timeout=30)
    assert _tabs_index(app) == before and app.session_state["apply_tab"] == "Sections"


def test_a_typed_delete_confirmation_does_not_carry_to_a_new_application(tmp_path, monkeypatch) -> None:
    _r21_database(tmp_path)
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.button(key="start_application").click().run(timeout=30)
    app.text_input(key="apply_delete_1").set_value("PAR-1").run(timeout=30)
    app.button(key="apply_delete_button").click().run(timeout=30)
    assert not app.exception and any("Deleted" in success.value for success in app.success)
    app.sidebar.radio[0].set_value("Find").run(timeout=30)
    app.button(key="start_application").click().run(timeout=30)
    assert not app.exception and app.selectbox(key="application_id").value == 1
    assert app.text_input(key="apply_delete_1").value == "" and app.button(key="apply_delete_button").disabled


def test_the_keys_of_a_deleted_application_are_its_own() -> None:
    from nih_grant_matcher.ui.apply_page import owned_by
    assert [key for key in ("apply_delete_1", "apply_export_1", "apply_text_1_specific-aims", "apply_base_1_project-narrative", "apply_acknowledge_1_project-summary", "apply_delete_11", "apply_text_11_specific-aims", "apply_section", "apply_signer", "apply_restore_1_button", "application_id") if owned_by(1, key)] == ["apply_delete_1", "apply_export_1", "apply_text_1_specific-aims", "apply_base_1_project-narrative", "apply_acknowledge_1_project-summary"]


def test_a_phased_award_says_why_it_cannot_be_started(tmp_path, monkeypatch) -> None:
    from helpers import opportunity
    store = OpportunityStore(tmp_path / "data" / "grants.sqlite3")
    try:
        store.upsert_scored(MLRelevanceScorer().score(replace_close(opportunity(instruments=("R21", "R33")))))
    finally:
        store.close()
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert not app.exception and app.button(key="start_application").disabled
    assert any("phased award" in caption.value for caption in app.caption)
