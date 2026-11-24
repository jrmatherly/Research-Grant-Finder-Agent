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
    assert any(caption.value.endswith("references. It holds no API key.") for caption in app.caption)


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


def test_a_call_id_in_another_applications_key_is_not_this_applications_id() -> None:
    from nih_grant_matcher.ui.apply_page import owned_by
    assert not owned_by(1, "apply_edit_2_specific-aims_1") and owned_by(2, "apply_edit_2_specific-aims_1")


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


def test_a_restore_after_a_save_from_another_tab_restores_nothing(tmp_path, monkeypatch) -> None:
    path = _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    for text in ("Aim 1.", "Aim 2."):
        app.text_area(key="apply_text_1_specific-aims").set_value(text)
        app.button(key="apply_save_button").click().run(timeout=30)
    store = OpportunityStore(path)
    try:
        store.add_revision(1, "specific-aims", 2, "applicant", "write", "Tab two.")
    finally:
        store.close()
    app.button(key="apply_restore_1_button").click().run(timeout=30)
    assert not app.exception and not any("Restored" in s.value for s in app.success)
    store = OpportunityStore(path)
    try:
        assert [r.text for r in store.revisions(1)] == ["Aim 1.", "Aim 2.", "Tab two."]
    finally:
        store.close()


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
    assert any('Your decision on "Research Strategy: at most 4 pages." was dropped, because the new text no longer has the sentence it came from.' in text.replace("\\", "") for text in shown)
    monkeypatch.setattr(GrantsGovClient, "full_announcement", lambda self, number: "")
    app.button(key="apply_fetch_button").click().run(timeout=30)
    assert not app.exception and any("Grant Matcher kept the copy it saved from Grants.gov" in text.replace("\\", "") and "The announcement saved earlier still applies" in text for text in (error.value for error in app.error))


def _subheaders(app):
    return [subheader.value for subheader in app.subheader]


def _ranking(app):
    return next(radio for radio in app.radio if radio.label == "Ranking")


def test_keeping_the_built_in_ranking_saves_a_name_and_changes_no_score(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.profile import ranks_like_builtin
    path = tmp_path / "data" / "grants.sqlite3"
    store = OpportunityStore(path)
    try:
        store.upsert_many([MLRelevanceScorer().score(_opp(1, "Machine learning for imaging")), MLRelevanceScorer().score(_opp(2, "Mitochondria in cardiac muscle"))])
    finally:
        store.close()
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    before = app.dataframe[0].value[["Opportunity Number", "Score"]].to_dict("records")
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    _press(app, "Set up my profile")
    assert _ranking(app).options == ["Rank with my own research", "Keep the built-in ranking"] and _ranking(app).value == "Rank with my own research"
    _ranking(app).set_value("Keep the built-in ranking")
    app.text_input[0].set_value("Ada Lovelace")
    _press(app, "Next")
    assert not app.exception and "5. What the writer reuses" in _subheaders(app)
    _press(app, "Back")
    assert "1. You" in _subheaders(app)
    _press(app, "Save profile")
    assert not app.exception
    store = OpportunityStore(path)
    try:
        saved = store.profile()
        assert saved.investigator == "Ada Lovelace" and ranks_like_builtin(saved)
    finally:
        store.close()
    sentence = "Ranking uses the built-in profile (machine learning and data science) for Ada Lovelace."
    assert sentence in [caption.value for caption in app.caption]
    _press(app, "Edit my profile")
    assert _ranking(app).value == "Keep the built-in ranking"
    _ranking(app).set_value("Rank with my own research")
    _press(app, "Next")
    assert "2. Your research" in _subheaders(app)
    app.sidebar.radio[0].set_value("Find").run(timeout=30)
    assert not app.exception and app.dataframe[0].value[["Opportunity Number", "Score"]].to_dict("records") == before
    captions = [caption.value for caption in app.caption]
    assert sentence in captions and captions[0] == "Run NIH Guide and Grants.gov searches, rank computational opportunities, and explore the results interactively."


def test_the_terms_step_offers_up_to_three_institutes(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    _press(app, "Set up my profile")
    _press(app, "Next")
    app.text_area[0].set_value("Mitochondria in the heart.")
    app.text_area[1].set_value("Measure mitochondrial fission in heart failure. Map cardiac muscle energetics. Test mitophagy in cardiomyocytes.")
    _press(app, "Next")
    assert "3. Your terms" in _subheaders(app)
    institutes = next(select for select in app.multiselect if select.label == "Your NIH institutes")
    assert "NHLBI, National Heart, Lung, and Blood Institute" in institutes.options and not any(option.startswith(("NIH,", "OD,")) for option in institutes.options)
    assert any("A record issued by NIH for several institutes gets no bonus." in caption.value for caption in app.caption)
    # The browser refuses a fourth choice, and Streamlit raises on one that reaches the server.
    assert institutes.max_selections == 3
    institutes.set_value(["NHLBI"])
    _press(app, "Next")
    assert not app.exception and "4. Preview" in _subheaders(app) and app.session_state["profile_draft"].institutes == ("NHLBI",)


def test_the_model_expander_saves_a_key_asks_for_consent_and_tests_the_connection(tmp_path, monkeypatch, post) -> None:
    from helpers import fixture
    from nih_grant_matcher import keys
    for name in ("GRANT_MATCHER_LLM_KEY", "GRANT_MATCHER_LLM_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(keys, "PLATFORM", "linux")
    path = _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.selectbox(key="apply_llm_provider").set_value("compatible").run(timeout=30)
    assert not app.exception and app.text_input(key="apply_llm_base_url").value == "http://localhost:11434/v1"
    app.text_input(key="apply_llm_key").input("sk-local-4f2a")
    app.button(key="apply_llm_save_key_button").click().run(timeout=30)
    assert not app.exception and any("ends in ...4f2a" in caption.value for caption in app.caption)
    assert "sk-local-4f2a" not in " ".join(element.value for element in [*app.markdown, *app.caption, *app.success])
    post.reply({"object": "list", "data": [{"id": "llama9", "object": "model"}]})
    app.button(key="apply_llm_list_button").click().run(timeout=30)
    app.selectbox(key="apply_llm_model").set_value("llama9").run(timeout=30)
    assert app.button(key="apply_llm_test_button").disabled
    app.checkbox(key="apply_llm_consent_localhost").check().run(timeout=30)
    post.reply(fixture("openai-ok"))
    app.button(key="apply_llm_test_button").click().run(timeout=30)
    assert not app.exception and any("answered" in success.value for success in app.success)
    assert post.headers["Authorization"] == "Bearer sk-local-4f2a" and post.body["model"] == "llama9"
    store = OpportunityStore(path)
    try:
        assert store.setting("consent:localhost") and store.setting("llm.model") == "llama9"
    finally:
        store.close()
    assert b"sk-local-4f2a" not in path.read_bytes()


def test_a_key_file_that_cannot_be_read_is_an_error_and_the_apply_view_still_draws(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher import keys
    for name in ("OPENAI_API_KEY", "OPENAI_API_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(keys, "PLATFORM", "linux")
    _r21_database(tmp_path, start=True)
    (tmp_path / "data" / "llm-keys.json").write_text("{not json", encoding="utf-8")
    app = _apply_view(tmp_path, monkeypatch)
    app.selectbox(key="apply_llm_provider").set_value("openai").run(timeout=30)
    assert not app.exception and any("cannot be read" in error.value for error in app.error)
    assert app.button(key="apply_fetch_button").label == "Fetch the full announcement"


def test_a_declined_keychain_is_asked_once_and_again_on_try_again(tmp_path, monkeypatch) -> None:
    from helpers import FakeSecurity
    from nih_grant_matcher import keys
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    fake = FakeSecurity()
    fake.exit_with = 51
    monkeypatch.setattr(keys, "PLATFORM", "darwin")
    monkeypatch.setattr(keys, "_run", fake)
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.selectbox(key="apply_llm_provider").set_value("claude").run(timeout=30)
    app.run(timeout=30)
    assert len(fake.argv) == 1 and not app.exception and any("declined" in error.value for error in app.error)
    fake.exit_with = None
    app.button(key="apply_llm_retry_button").click().run(timeout=30)
    assert len(fake.argv) == 2 and not app.exception and not app.error and any("No key saved." in caption.value for caption in app.caption)


def test_test_connection_refuses_a_host_without_consent(tmp_path, monkeypatch, post) -> None:
    from helpers import fixture
    from nih_grant_matcher import keys
    from nih_grant_matcher.ui import apply_page
    monkeypatch.setattr(keys, "get", lambda provider, data_dir: None)
    store = OpportunityStore(tmp_path / "g.sqlite3")
    # The Base URL changed in the same rerun as the click, so only the old host has consent.
    for name, value in (("llm.provider", "compatible"), ("llm.base_url", "http://gpu.example:8000/v1"), ("llm.model", "llama9"), ("consent:localhost", "2026-11-23T00:00:00")):
        store.set_setting(name, value)
    post.reply(fixture("openai-ok"))
    try:
        with pytest.raises(ValueError, match="Agree to send text to gpu.example first"):
            apply_page._test_connection(store)
    finally:
        store.close()
    assert post.calls == 0


def _openai_reply(text: str) -> dict:
    return {"model": "llama9", "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 9, "completion_tokens": 5}}


def test_polish_shows_a_proposal_that_changes_nothing_until_accepted_and_the_statement_names_it(tmp_path, monkeypatch, post) -> None:
    from nih_grant_matcher import keys
    monkeypatch.setattr(keys, "get", lambda provider, data_dir: None)
    path = _r21_database(tmp_path, start=True)
    store = OpportunityStore(path)
    try:
        for name, value in (("llm.provider", "compatible"), ("llm.model", "llama9"), ("consent:localhost", "2026-11-23T00:00:00")):
            store.set_setting(name, value)
        store.add_revision(1, "specific-aims", None, "applicant", "write", "We study heart cells.")
    finally:
        store.close()
    app = _apply_view(tmp_path, monkeypatch)
    post.reply(_openai_reply("We study *cardiac* muscle cells."))
    app.button(key="apply_polish_button").click().run(timeout=30)
    assert not app.exception and post.calls == 1 and "We study heart cells." in post.body["messages"][1]["content"]
    assert app.text_area(key="apply_text_1_specific-aims").value == "We study heart cells."
    assert any("~~heart~~" in m.value and "\\*cardiac\\*" in m.value for m in app.markdown)
    app.run(timeout=30)
    assert app.button(key="apply_accept_button")
    app.button(key="apply_accept_button").click().run(timeout=30)
    assert not app.exception and app.text_area(key="apply_text_1_specific-aims").value == "We study *cardiac* muscle cells."
    assert any("I used llama9 (compatible) to polish the Specific Aims." in m.value.replace("\\", "") for m in app.markdown)
    app.toggle(key="apply_disclosure_1").set_value(False).run(timeout=30)
    assert not app.exception and not any("I used llama9" in m.value for m in app.markdown)


def test_polish_is_not_offered_without_a_model(tmp_path, monkeypatch) -> None:
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    assert not app.exception and not [b for b in app.button if b.key in ("apply_polish_button", "apply_revise_button")]


def test_a_revision_is_named_a_revision_on_the_page_and_in_the_log(tmp_path, monkeypatch, post) -> None:
    from nih_grant_matcher import keys
    monkeypatch.setattr(keys, "get", lambda provider, data_dir: None)
    path = _r21_database(tmp_path, start=True)
    store = OpportunityStore(path)
    try:
        for name, value in (("llm.provider", "compatible"), ("llm.model", "llama9"), ("consent:localhost", "2026-11-23T00:00:00")):
            store.set_setting(name, value)
        store.add_revision(1, "specific-aims", None, "applicant", "write", "We study heart cells.")
    finally:
        store.close()
    app = _apply_view(tmp_path, monkeypatch)
    app.text_input(key="apply_instruction_1_specific-aims").set_value("Name the cells.")
    post.reply(_openai_reply("We study cardiac muscle cells."))
    app.button(key="apply_revise_button").click().run(timeout=30)
    assert not app.exception and any("A model's revision, proposal 1" in m.value for m in app.markdown)
    app.button(key="apply_accept_button").click().run(timeout=30)
    assert not app.exception and any("A model's revision on" in m.value for m in app.markdown)
    assert not any("A model's revise" in m.value for m in app.markdown)


def test_each_wizard_field_holds_the_profiles_limit_while_typing(tmp_path, monkeypatch) -> None:
    import json
    column_limit = lambda app, name: json.loads(app.dataframe[0].proto.columns).get(name, {}).get("type_config", {}).get("max_chars")
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    _press(app, "Set up my profile")
    limits = {t.label: t.max_chars for t in app.text_input}
    _press(app, "Next")
    limits.update({t.label: t.max_chars for t in app.text_area})
    app.text_area[1].set_value("Measure mitochondrial fission in heart failure. Map cardiac muscle energetics. Test mitophagy in cardiomyocytes.")
    _press(app, "Next")
    limits["Term"] = column_limit(app, "Term")
    _press(app, "Next")
    _press(app, "Next")
    limits.update({t.label: t.max_chars for t in app.text_area})
    limits["Citation"] = column_limit(app, "Citation")
    expected = {"Name": 200, "Institution": 200, "Research summary": 6000, "Term": 80, "Expertise": 6000, "Resources": 6000, "Citation": 1000}
    assert {name: limits.get(name) for name in expected} == expected


def test_a_built_in_ranking_with_no_name_is_described_by_its_background() -> None:
    from nih_grant_matcher.profile import Profile
    from nih_grant_matcher.ui.profile_page import profile_sentence
    assert profile_sentence(Profile(expertise="Cardiac imaging.")) == "Ranking uses the built-in profile (machine learning and data science) with your background."


def test_saving_with_the_built_in_ranking_says_the_ranking_is_kept(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    _press(app, "Set up my profile")
    _ranking(app).set_value("Keep the built-in ranking")
    app.text_input[0].set_value("Ada Lovelace")
    _press(app, "Save profile")
    assert not app.exception and [s.value for s in app.success] == ["Saved your profile. The Find view keeps the built-in ranking."]


def test_leaving_the_built_in_ranking_starts_a_new_ranking_and_keeps_the_name(tmp_path, monkeypatch) -> None:
    from dataclasses import replace
    from nih_grant_matcher.profile import BUILTIN_PROFILE
    path = tmp_path / "data" / "grants.sqlite3"
    store = OpportunityStore(path)
    try:
        store.save_profile(replace(BUILTIN_PROFILE, investigator="Ada Lovelace", expertise="Cardiac imaging."))
    finally:
        store.close()
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    _press(app, "Edit my profile")
    _ranking(app).set_value("Rank with my own research")
    _press(app, "Next")
    assert not app.exception and (app.text_area[0].value, app.text_area[1].value) == ("", "")
    app.text_area[0].set_value("Mitochondria in the heart.")
    aims = ("Measure mitochondrial fission in heart failure.", "Map cardiac muscle energetics.", "Test mitophagy in cardiomyocytes.")
    app.text_area[1].set_value(" ".join(aims))
    _press(app, "Next")
    assert not set(app.session_state["profile_draft"].keywords) & set(BUILTIN_PROFILE.keywords)
    for _ in range(2):
        _press(app, "Next")
    _press(app, "Save profile")
    assert not app.exception
    store = OpportunityStore(path)
    try:
        saved = store.profile()
    finally:
        store.close()
    assert (saved.investigator, saved.expertise, saved.examples, saved.focus, saved.examples_name) == ("Ada Lovelace", "Cardiac imaging.", aims, "profile", "your example sentences")
    assert not set(saved.keywords) & set(BUILTIN_PROFILE.keywords)
    # A ranking of the applicant's own stays when the radio is touched.
    _press(app, "Edit my profile")
    _ranking(app).set_value("Rank with my own research")
    _press(app, "Next")
    assert app.text_area[1].value == "\n".join(aims)


def test_a_model_share_that_rounds_to_zero_reads_less_than_1_percent_under_the_section(tmp_path, monkeypatch) -> None:
    path, words = _r21_database(tmp_path, start=True), [f"w{k}" for k in range(300)]
    store = OpportunityStore(path)
    try:
        mine = store.add_revision(1, "specific-aims", None, "applicant", "write", " ".join(words))
        words[0] = "polished"
        call = store.add_call(1, "specific-aims", "polish", "fake", "fake-1", "s", "p", " ".join(words), parent_id=mine.id)
        store.add_revision(1, "specific-aims", mine.id, "model", "polish", " ".join(words), call.id)
    finally:
        store.close()
    app = _apply_view(tmp_path, monkeypatch)
    assert not app.exception and "You wrote more than 99 percent of the words. A model drafted or revised 0 percent, and a model polished less than 1 percent." in [c.value for c in app.caption]


def test_a_refused_restore_says_nothing_was_restored(tmp_path, monkeypatch) -> None:
    path = _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    for text in ("Aim 1.", "Aim 2."):
        app.text_area(key="apply_text_1_specific-aims").set_value(text)
        app.button(key="apply_save_button").click().run(timeout=30)
    store = OpportunityStore(path)
    try:
        store.add_revision(1, "specific-aims", 2, "applicant", "write", "Tab two.")
    finally:
        store.close()
    app.button(key="apply_restore_1_button").click().run(timeout=30)
    warnings = " ".join(w.value for w in app.warning)
    assert not app.exception and "changed in another tab, so nothing was restored" in warnings and "not saved" not in warnings


def test_next_from_the_aims_step_names_a_sentence_over_the_limit(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.profile import MAX_SENTENCE
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    _press(app, "Set up my profile")
    _press(app, "Next")
    long = "Measure " + "very " * 150 + "long fission."
    app.text_area[1].set_value(f"Map cardiac energetics. {long} Test mitophagy.")
    _press(app, "Next")
    assert not app.exception and app.session_state["profile_step"] == 1
    assert any(f'"{long[:60]}' in e.value and f"{MAX_SENTENCE} characters" in e.value for e in app.error)


def test_the_wizard_opens_a_profile_saved_over_a_limit_whole_and_refuses_to_save_it(tmp_path, monkeypatch) -> None:
    from helpers import save_like_main
    from nih_grant_matcher.ui.markdown import escape_markdown
    path = tmp_path / "data" / "grants.sqlite3"
    save_like_main(path, investigator="A" * 250, research_summary="s" * 6500, examples=["Map cardiac energetics.", "Test mitophagy.", "Measure fission."])
    store = OpportunityStore(path)
    try:
        before = store.profile()
    finally:
        store.close()
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio[0].set_value("Profile").run(timeout=30)
    assert not app.exception and not app.error and any("the profile of " + "A" * 250 in c.value for c in app.caption)
    _press(app, "Edit my profile")
    assert app.text_input[0].value == "A" * 250
    _press(app, "Next")
    assert app.text_area[0].value == "s" * 6500
    for _ in range(3):
        _press(app, "Next")
    assert [t.value for t in app.text_area if t.label == "Resources"] == ["r" * 7200]
    _press(app, "Save profile")
    assert not app.exception and [e.value for e in app.error] == [escape_markdown("investigator: at most 200 characters")]
    store = OpportunityStore(path)
    try:
        assert store.profile() == before
    finally:
        store.close()


def test_accepting_with_edits_a_proposal_already_accepted_elsewhere_says_the_edits_were_not_saved(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher.ui.markdown import escape_markdown
    from nih_grant_matcher.writer import Workspace
    path = _r21_database(tmp_path, start=True)
    store = OpportunityStore(path)
    try:
        mine = store.add_revision(1, "specific-aims", None, "applicant", "write", "We study heart cells.")
        call = store.add_call(1, "specific-aims", "polish", "fake", "fake-1", "s", "p", "We study cardiac muscle cells.", parent_id=mine.id)
    finally:
        store.close()
    app = _apply_view(tmp_path, monkeypatch)
    app.text_area(key=f"apply_edit_1_specific-aims_{call.id}").set_value("We study our cardiac cells.")
    store = OpportunityStore(path)
    try:
        Workspace(store, 1).accept(call.id)
    finally:
        store.close()
    app.button(key="apply_accept_edited_button").click().run(timeout=30)
    assert not app.exception and any(escape_markdown(f"Proposal {call.id} was already accepted, so your edits were not saved.") in e.value for e in app.error)
    assert not any("Accepted the proposal" in x.value for x in app.success)


def _page_notices(app):
    # The container right under the Apply header holds the notices of the actions, above the tabs, where every tab shows them.
    children = list(app.main.children.values())
    at = next(i for i, c in enumerate(children) if type(c).__name__ == "Header" and c.value == "Apply")
    return [e.value for kind in ("success", "warning", "error") for e in children[at + 1].get(kind)]


def test_a_refused_restore_says_so_above_the_tabs(tmp_path, monkeypatch) -> None:
    path = _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    for text in ("Aim 1.", "Aim 2."):
        app.text_area(key="apply_text_1_specific-aims").set_value(text)
        app.button(key="apply_save_button").click().run(timeout=30)
    store = OpportunityStore(path)
    try:
        store.add_revision(1, "specific-aims", 2, "applicant", "write", "Tab two.")
    finally:
        store.close()
    app.button(key="apply_restore_1_button").click().run(timeout=30)
    assert not app.exception and _page_notices(app) == ["This section changed in another tab, so nothing was restored. The page now shows the current text."]


def test_the_sections_tab_says_what_the_model_set_up_still_needs(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher import keys
    for name in ("OPENAI_API_KEY", "OPENAI_API_KEY_FILE", "GRANT_MATCHER_LLM_KEY", "GRANT_MATCHER_LLM_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(keys, "PLATFORM", "linux")
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    needs = lambda: [c.value for c in app.caption if c.value.startswith("Polish and Revise need")]
    assert not app.exception and needs() == ["Polish and Revise need a model. No provider is chosen. Set it up under Model at the top of this page."]
    app.selectbox(key="apply_llm_provider").set_value("openai").run(timeout=30)
    assert needs() == ["Polish and Revise need a model. No API key was found for the provider. Set it up under Model at the top of this page."]
    app.selectbox(key="apply_llm_provider").set_value("compatible").run(timeout=30)
    assert needs() == ["Polish and Revise need a model. No model is chosen. Set it up under Model at the top of this page."]
    assert not any(b.key == "apply_polish_button" for b in app.button)


@pytest.mark.parametrize("key, ending", [("sk-4f2a", None), ("abcdefgh4f2a", "...4f2a"), ("sk-local-x4f2a", "...4f2a")])
def test_the_key_line_shows_an_ending_only_for_a_key_of_12_characters_or_more(tmp_path, monkeypatch, key, ending) -> None:
    from nih_grant_matcher import keys
    for name in ("GRANT_MATCHER_LLM_KEY", "GRANT_MATCHER_LLM_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(keys, "PLATFORM", "linux")
    _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.selectbox(key="apply_llm_provider").set_value("compatible").run(timeout=30)
    app.text_input(key="apply_llm_key").input(key)
    app.button(key="apply_llm_save_key_button").click().run(timeout=30)
    line = next(c.value for c in app.caption if c.value.startswith("Saved"))
    assert not app.exception and (line.endswith(f", ends in {ending}.") if ending else "ends in" not in line and "4f2a" not in line)


def test_the_consent_box_is_drawn_ticked_on_the_run_that_records_consent(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher import keys
    for name in ("GRANT_MATCHER_LLM_KEY", "GRANT_MATCHER_LLM_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(keys, "PLATFORM", "linux")
    path = _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    app.selectbox(key="apply_llm_provider").set_value("compatible").run(timeout=30)
    app.checkbox(key="apply_llm_consent_localhost").check().run(timeout=30)
    box = app.checkbox(key="apply_llm_consent_localhost")
    assert not app.exception and box.value and box.disabled
    app.run(timeout=30)
    assert app.checkbox(key="apply_llm_consent_localhost").value
    store = OpportunityStore(path)
    try:
        assert store.setting("consent:localhost")
    finally:
        store.close()


def test_the_model_expander_stays_open_until_the_set_up_is_complete(tmp_path, monkeypatch) -> None:
    from nih_grant_matcher import keys
    for name in ("GRANT_MATCHER_LLM_KEY", "GRANT_MATCHER_LLM_KEY_FILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(keys, "PLATFORM", "linux")
    path = _r21_database(tmp_path, start=True)
    app = _apply_view(tmp_path, monkeypatch)
    opened = lambda: next(e for e in app.expander if e.label == "Model").proto.expanded
    assert opened()
    app.selectbox(key="apply_llm_provider").set_value("compatible").run(timeout=30)
    assert not app.exception and opened()
    store = OpportunityStore(path)
    try:
        store.set_setting("llm.model", "llama9")
    finally:
        store.close()
    app.run(timeout=30)
    assert opened()
    app.checkbox(key="apply_llm_consent_localhost").check().run(timeout=30)
    assert not app.exception and not opened()
