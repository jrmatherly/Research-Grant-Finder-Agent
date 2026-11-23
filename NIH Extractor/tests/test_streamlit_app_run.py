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


def _tabs(app):
    return app.main.children[_tabs_index(app)].proto.id


# The open tab lives in the browser and follows the tabs block's id, so a run that keeps the place and the id keeps the tab.
def test_a_notice_does_not_move_the_tabs_or_change_their_id(tmp_path, monkeypatch) -> None:
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    before = (_tabs_index(app), _tabs(app))
    app.text_area(key="apply_text_1_specific-aims").set_value("Aim 1.")
    app.button(key="apply_save_button").click().run(timeout=30)
    assert not app.exception and app.success
    assert (_tabs_index(app), _tabs(app)) == before
    app.selectbox(key="apply_section").set_value("project-narrative").run(timeout=30)
    assert (_tabs_index(app), _tabs(app)) == before


def test_a_rerun_does_not_send_a_value_over_what_the_applicant_is_typing(tmp_path, monkeypatch) -> None:
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.run(timeout=30)
    assert not app.exception
    assert [app.text_area(key=key).proto.set_value for key in ("apply_text_1_specific-aims", "apply_fact_text")] == [False, False]
    assert not app.text_input(key="apply_fact_label").proto.set_value and not app.selectbox(key="apply_section").proto.set_value


def test_find_and_apply_values_survive_a_view_switch(tmp_path, monkeypatch) -> None:
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.text_input(key="apply_export_1").set_value("elsewhere").run(timeout=30)
    app.sidebar.radio[0].set_value("Find").run(timeout=30)
    app.sidebar.text_input(key="find_keyword").set_value("imaging").run(timeout=30)
    app.sidebar.radio[0].set_value("Apply").run(timeout=30)
    assert app.text_input(key="apply_export_1").value == "elsewhere"
    app.sidebar.radio[0].set_value("Find").run(timeout=30)
    assert not app.exception and app.sidebar.text_input(key="find_keyword").value == "imaging"


def test_a_start_or_a_delete_opens_the_first_tab_and_a_switch_keeps_it(tmp_path, monkeypatch) -> None:
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    first = _tabs(app)
    app.sidebar.radio[0].set_value("Find").run(timeout=30)
    app.checkbox[0].check().run(timeout=30)
    app.button(key="start_application").click().run(timeout=30)
    started = _tabs(app)
    assert not app.exception and started != first
    app.selectbox(key="application_id").set_value(1).run(timeout=30)
    assert _tabs(app) == started
    app.text_input(key="apply_delete_1").set_value("PAR-1").run(timeout=30)
    app.button(key="apply_delete_button").click().run(timeout=30)
    assert not app.exception and _tabs(app) not in (first, started)


def test_a_stale_warning_does_not_follow_a_deleted_application(tmp_path, monkeypatch) -> None:
    path = _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.text_area(key="apply_text_1_specific-aims").set_value("Aim 1.")
    app.button(key="apply_save_button").click().run(timeout=30)
    store = OpportunityStore(path)
    try:
        store.add_revision(1, "specific-aims", 1, "applicant", "write", "Aim 1 from elsewhere.")
    finally:
        store.close()
    app.text_area(key="apply_text_1_specific-aims").set_value("Aim 1, mine.")
    app.button(key="apply_save_button").click().run(timeout=30)
    stale = "This section changed after you opened it"
    assert any(stale in warning.value for warning in app.warning)
    app.text_input(key="apply_delete_1").set_value("PAR-1").run(timeout=30)
    app.button(key="apply_delete_button").click().run(timeout=30)
    assert "apply_stale" not in app.session_state and "apply_text_1_specific-aims" not in app.session_state
    app.sidebar.radio[0].set_value("Find").run(timeout=30)
    app.button(key="start_application").click().run(timeout=30)
    assert not app.exception and app.selectbox(key="application_id").value == 2
    assert not any(stale in warning.value for warning in app.warning)


def test_a_typed_delete_confirmation_does_not_carry_to_a_new_application(tmp_path, monkeypatch) -> None:
    _r21_database(tmp_path)
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.button(key="start_application").click().run(timeout=30)
    app.text_input(key="apply_delete_1").set_value("PAR-1").run(timeout=30)
    app.button(key="apply_delete_button").click().run(timeout=30)
    assert not app.exception and any("Deleted" in success.value for success in app.success)
    assert "apply_delete_1" not in app.session_state
    app.sidebar.radio[0].set_value("Find").run(timeout=30)
    app.button(key="start_application").click().run(timeout=30)
    assert not app.exception and app.selectbox(key="application_id").value == 2
    assert app.text_input(key="apply_delete_2").value == "" and app.button(key="apply_delete_button").disabled


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


SECTION_IV = "Section IV. Application and Submission Information\nThe Research Strategy is limited to 4 pages.\nSection V. Application Review Information\nx" + " More text." * 100


def _page_text(app):
    return " ".join(element.value for element in [*app.markdown, *app.caption, *app.info, *app.success, *app.warning, *app.error]).replace("\\", "")


def test_an_announcement_with_no_section_iv_is_named_on_each_tab(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.clients import GrantsGovClient, NihGuideClient
    monkeypatch.setattr(NihGuideClient, "doctext", lambda self, number: ("A notice with no headings at all. " * 40, "1"))
    monkeypatch.setattr(GrantsGovClient, "full_announcement", lambda self, number: "")
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.button(key="apply_fetch_button").click().run(timeout=30)
    assert not app.exception
    said = "found no Section IV in this text and read no requirement from it"
    assert any(said in success.value for success in app.success)
    assert sum(said in info.value for info in app.info) == 2 and not any("found no added requirement" in info.value for info in app.info)


def test_each_apply_button_does_its_one_thing(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.clients import GrantsGovClient, NihGuideClient
    monkeypatch.setattr(NihGuideClient, "doctext", lambda self, number: (SECTION_IV, "1"))
    monkeypatch.setattr(GrantsGovClient, "full_announcement", lambda self, number: "")
    path = _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.button(key="apply_fetch_button").click().run(timeout=30)
    assert not app.exception and any("Saved the announcement from the NIH Guide" in s.value for s in app.success)
    assert "Research Strategy: at most 4 pages." in _page_text(app) and "Not yet decided." in _page_text(app)
    app.button(key="apply_confirm_1_button").click().run(timeout=30)
    assert not app.exception and "Confirmed." in _page_text(app) and app.button(key="apply_confirm_1_button").disabled
    app.button(key="apply_reject_1_button").click().run(timeout=30)
    assert not app.exception and "Rejected." in _page_text(app) and app.button(key="apply_reject_1_button").disabled
    app.selectbox(key="apply_fact_kind").set_value("aim")
    app.text_area(key="apply_fact_text").set_value("Map heart cells.")
    app.button(key="apply_add_fact_button").click().run(timeout=30)
    assert not app.exception and any("Added input 1 under aim." in s.value for s in app.success) and "Map heart cells" in _page_text(app)
    app.button(key="apply_retire_1_button").click().run(timeout=30)
    assert not app.exception and "Map heart cells" not in _page_text(app)
    for text in ("Aim 1.", "Aim 2."):
        app.text_area(key="apply_text_1_specific-aims").set_value(text)
        app.button(key="apply_save_button").click().run(timeout=30)
    app.button(key="apply_restore_1_button").click().run(timeout=30)
    assert not app.exception and any("Restored the text of revision 1 as revision 3." in s.value for s in app.success)
    assert app.text_area(key="apply_text_1_specific-aims").value == "Aim 1."
    app.text_input(key="apply_export_1").set_value("out").run(timeout=30)
    app.button(key="apply_export_button").click().run(timeout=30)
    folder = (tmp_path / "out").resolve()
    assert not app.exception and (folder / "DRAFT-specific-aims.md").exists()
    assert any(str(folder) in s.value.replace("\\", "") for s in app.success)
    store = OpportunityStore(path)
    try:
        store.add_revision(1, "specific-aims", 3, "applicant", "write", "Aim 1 from elsewhere.")
    finally:
        store.close()
    app.text_area(key="apply_text_1_specific-aims").set_value("Aim 1, mine.")
    app.button(key="apply_save_button").click().run(timeout=30)
    assert any("changed after you opened it" in w.value for w in app.warning)
    app.button(key="apply_load_newest_button").click().run(timeout=30)
    assert not app.exception and app.text_area(key="apply_text_1_specific-aims").value == "Aim 1 from elsewhere."
    assert not any("changed after you opened it" in w.value for w in app.warning)


def test_a_stale_sign_off_says_nothing_was_signed(tmp_path, monkeypatch) -> None:
    path = _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.selectbox(key="apply_section").set_value("project-narrative").run(timeout=30)
    app.text_area(key="apply_text_1_project-narrative").set_value("One. Two.")
    app.button(key="apply_save_button").click().run(timeout=30)
    store = OpportunityStore(path)
    try:
        store.add_revision(1, "project-narrative", 1, "applicant", "write", "One. Two. Three.")
    finally:
        store.close()
    app.text_input(key="apply_signer").set_value("A. Applicant")
    app.button(key="apply_sign_button").click().run(timeout=30)
    assert not app.exception
    assert any("nothing was signed" in w.value for w in app.warning) and not any("not saved" in w.value for w in app.warning)
    store = OpportunityStore(path)
    try:
        assert store.signoffs(1) == []
    finally:
        store.close()


def test_the_delete_caption_says_exported_files_stay(tmp_path, monkeypatch) -> None:
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    assert any("Files you exported stay where you exported them." in caption.value for caption in app.caption)


def test_the_terms_table_names_each_term_it_drops_or_merges() -> None:
    import pandas as pd
    from nih_grant_matcher.ui.profile_page import read_terms
    table = pd.DataFrame({"Term": ["cardiac", "Cardiac", "fibrosis", "valve", None, "  "], "Weight": [12, 18, None, 9, 5, 4]})
    assert read_terms(table) == ({"cardiac": 18, "valve": 9}, ["fibrosis"], [("cardiac", "Cardiac", 18)])
    assert read_terms(pd.DataFrame({"Term": ["valve"], "Weight": [9]})) == ({"valve": 9}, [], [])


def test_the_wizard_warns_about_the_terms_it_dropped_or_merged(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.profile import Profile
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    app.session_state["profile_step"], app.session_state["profile_draft"] = 2, Profile(keywords={"cardiac": 12, "Cardiac": 18, "fibrosis": None, "valve": 9}, examples=("One.", "Two.", "Three."), focus="profile", examples_name="your example sentences")
    app.run(timeout=30)
    next(button for button in app.button if button.label == "Next").click().run(timeout=30)
    assert not app.exception and app.session_state["profile_draft"].keywords == {"cardiac": 18, "valve": 9}
    (warning,) = [w.value for w in app.warning if "fibrosis" in w.value]
    assert "fibrosis had no weight" in warning and "cardiac and Cardiac are one term" in warning and "18" in warning


def test_a_refused_start_stays_in_the_find_view_with_the_error(tmp_path, monkeypatch) -> None:
    import os
    path = _r21_database(tmp_path, start=True)
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.checkbox[0].check().run(timeout=30)
    path.chmod(0o444)
    if getattr(os, "geteuid", lambda: 1)() == 0:
        pytest.skip("root writes to a read-only file")
    try:
        app.button(key="start_application").click().run(timeout=30)
    finally:
        path.chmod(0o644)
    assert not app.exception and app.session_state["view"] == "Find"
    assert any("readonly" in error.value.replace("\\", "") for error in app.error)
    app.sidebar.radio[0].set_value("Apply").run(timeout=30)
    assert not any("readonly" in error.value.replace("\\", "") for error in app.error)


def test_a_saved_section_of_white_space_is_not_called_clean(tmp_path, monkeypatch) -> None:
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.selectbox(key="apply_section").set_value("project-narrative").run(timeout=30)
    app.text_area(key="apply_text_1_project-narrative").set_value("   ")
    app.button(key="apply_save_button").click().run(timeout=30)
    assert not app.exception and any("Saved revision 1" in success.value for success in app.success)
    assert "No text saved yet." in [info.value for info in app.info] and not any("found nothing to fix" in success.value for success in app.success)


def _signoffs(path):
    store = OpportunityStore(path)
    try:
        return store.signoffs(1)
    finally:
        store.close()


def test_signing_a_clean_section_shows_it_signed(tmp_path, monkeypatch) -> None:
    path = _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.selectbox(key="apply_section").set_value("project-narrative").run(timeout=30)
    app.text_area(key="apply_text_1_project-narrative").set_value("One. Two.")
    app.button(key="apply_save_button").click().run(timeout=30)
    app.text_input(key="apply_signer").set_value("A. Applicant")
    app.button(key="apply_sign_button").click().run(timeout=30)
    assert not app.exception and any("Signed off at revision 1." in caption.value for caption in app.caption)
    assert [s.signer for s in _signoffs(path)] == ["A. Applicant"]


def test_signing_unsaved_text_asks_for_a_save_and_signs_nothing(tmp_path, monkeypatch) -> None:
    path = _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.selectbox(key="apply_section").set_value("project-narrative").run(timeout=30)
    app.text_area(key="apply_text_1_project-narrative").set_value("One. Two.")
    app.button(key="apply_save_button").click().run(timeout=30)
    app.text_area(key="apply_text_1_project-narrative").set_value("One. Two. Three.")
    app.text_input(key="apply_signer").set_value("A. Applicant")
    app.button(key="apply_sign_button").click().run(timeout=30)
    assert not app.exception and any("Save your text before you sign off" in error.value for error in app.error)
    assert _signoffs(path) == []


def test_a_stale_save_keeps_the_applicants_text_in_the_box(tmp_path, monkeypatch) -> None:
    path = _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.text_area(key="apply_text_1_specific-aims").set_value("Aim 1.")
    app.button(key="apply_save_button").click().run(timeout=30)
    store = OpportunityStore(path)
    try:
        store.add_revision(1, "specific-aims", 1, "applicant", "write", "Aim 1 from elsewhere.")
    finally:
        store.close()
    app.text_area(key="apply_text_1_specific-aims").set_value("Aim 1, mine.")
    app.button(key="apply_save_button").click().run(timeout=30)
    assert any("changed after you opened it" in warning.value for warning in app.warning)
    assert app.text_area(key="apply_text_1_specific-aims").value == "Aim 1, mine."


def test_a_fetch_that_both_sources_fail_says_the_standing_rules_apply(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.clients import ApiError, GrantsGovClient, NihGuideClient
    def down(self, number):
        raise ApiError("timed out")
    monkeypatch.setattr(NihGuideClient, "doctext", down)
    monkeypatch.setattr(GrantsGovClient, "full_announcement", down)
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.button(key="apply_fetch_button").click().run(timeout=30)
    assert not app.exception and any("The standing rules of the grant type still apply." in error.value.replace("\\", "") for error in app.error)


def test_a_save_that_leaves_a_finding_shows_it_on_the_sections_tab(tmp_path, monkeypatch) -> None:
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.text_area(key="apply_text_1_specific-aims").set_value("Aim 1. See https://example.org for more.")
    app.button(key="apply_save_button").click().run(timeout=30)
    assert not app.exception and any("NIH allows a link only where the announcement says so." in warning.value.replace("\\", "") for warning in app.warning)


def test_a_workspace_notice_is_on_the_page(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.writer import Workspace
    path = _r21_database(tmp_path, start=True)
    store = OpportunityStore(path)
    try:
        ws = Workspace(store, 1)
        fact = ws.add_fact("reference", "Smith J. Heart cells. 2021.", label="smith2021")
        ws.sign("specific-aims", "A. Applicant", ws.write("specific-aims", "As we showed [@smith2021].", parent=None).id)
        ws.retire_fact(fact.id)
    finally:
        store.close()
    app = _apply_view(tmp_path, monkeypatch)
    assert not app.exception and any("is a draft again" in warning.value for warning in app.warning)


def test_a_fetch_from_grants_gov_replaces_a_saved_guide_copy_and_names_a_dropped_decision(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.clients import GrantsGovClient, NihGuideClient
    _r21_database(tmp_path, start=True)
    monkeypatch.setattr(NihGuideClient, "doctext", lambda self, number: (SECTION_IV, "360675"))
    monkeypatch.setattr(GrantsGovClient, "full_announcement", lambda self, number: "")
    app = _apply_view(tmp_path, monkeypatch)
    app.button(key="apply_fetch_button").click().run(timeout=30)
    app.button(key="apply_confirm_1_button").click().run(timeout=30)
    monkeypatch.setattr(GrantsGovClient, "full_announcement", lambda self, number: "<p>" + "From Grants.gov. " * 100 + "</p>")
    app.button(key="apply_fetch_button").click().run(timeout=30)
    shown = [success.value for success in app.success]
    assert not app.exception and not app.error and any("Saved the announcement from Grants.gov." in text for text in shown)
    assert any("Your decision on Research Strategy\\: at most 4 pages\\. was dropped, because the new text no longer has the sentence it came from." in text for text in shown)
