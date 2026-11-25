import hashlib
import json
from pathlib import Path
from streamlit.testing.v1 import AppTest
from nih_grant_matcher.profile import Profile
from nih_grant_matcher.store import OpportunityStore
from nih_grant_matcher.ui import tour
from nih_grant_matcher.ui.profile_page import STEPS, saved_profile

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"
UI = Path(tour.__file__).parent
PINS = {"driver.js.iife.js": "9ef0eb2b57694145f881c225e61c988df73c03da36f3b2b176de744c17cf1e0d", "driver.css": "9b47907a54c7629054ff09e5fbb7bcd139d672f69efd39df47862f337a3f9a9e", "driver.js.LICENSE": "ec3ce3a08736fefd6a03a6d5b52b0705e6919fe06de9d7bd3fb63dcfb492d76d"}

def test_the_vendored_files_are_those_of_driver_js_1_14_0() -> None:
    assert {name: hashlib.sha256((tour.VENDOR / name).read_bytes()).hexdigest() for name in PINS} == PINS

def test_streamlit_reads_the_script_and_the_styles_as_content_not_as_paths() -> None:
    # Streamlit takes a one-line string that holds a slash for a file path, and the vendored stylesheet is one line.
    from streamlit.components.v2.component_path_utils import ComponentPathUtils
    assert ComponentPathUtils.looks_like_inline_content(tour.script())
    assert ComponentPathUtils.looks_like_inline_content(tour.styles())

def test_the_styles_put_the_overlay_above_the_sidebar() -> None:
    assert ".driver-overlay{z-index:1000000!important}" in tour.styles()

def test_every_step_points_at_a_key_that_its_view_draws() -> None:
    drawn = {"Find": APP.read_text(encoding="utf-8"), "Profile": (UI / "profile_page.py").read_text(encoding="utf-8"), "Settings": (UI / "settings_page.py").read_text(encoding="utf-8") + (UI / "apply_page.py").read_text(encoding="utf-8")}
    for step in tour.TOUR_STEPS:
        # Every view draws the View control, and the wizard draws one keyed box for the step it is on.
        source, key = (drawn["Find"], "view") if step.key == "view" else (drawn[step.view], step.key)
        assert f'key="{key}"' in source or (step.wizard is not None and key == f"profile_wizard_{step.wizard}" and 'key=f"profile_wizard_{step}"' in source), step
    assert [step.wizard for step in tour.TOUR_STEPS if step.wizard is not None] == list(range(len(STEPS)))

def test_the_tour_starts_on_find_and_ends_by_saying_where_an_application_starts() -> None:
    first, last = tour.TOUR_STEPS[0], tour.TOUR_STEPS[-1]
    assert (first.view, first.key) == ("Find", "view") and [view for view in dict.fromkeys(step.view for step in tour.TOUR_STEPS)] == ["Find", "Profile", "Settings"]
    assert "Apply holds the applications you start." in last.text and "Start application" in last.text

def test_the_popovers_use_no_dash_and_no_colon() -> None:
    assert not [step.title for step in tour.TOUR_STEPS if any(mark in step.title + step.text for mark in ("\u2014", "\u2013", " - ", ":"))]

def _show(app, step) -> None:
    # AppTest's session state has no setdefault, so the tour writes a dictionary and the test copies it over.
    state = {key: app.session_state[key] for key in tour.KEPT if key in app.session_state}
    tour.show(state, step)
    for key, value in state.items():
        app.session_state[key] = value
    app.run(timeout=30)

def test_every_step_draws_its_place_for_a_user_with_no_profile_and_saves_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.button(key="tour_start").click().run(timeout=30)
    for step in tour.TOUR_STEPS:
        _show(app, step)
        assert not app.exception and app.session_state["view"] == step.view, step
        assert [h.value for h in app.subheader if h.value[:1].isdigit()] == ([f"{step.wizard + 1}. {STEPS[step.wizard]}"] if step.wizard is not None else []), step
    assert saved_profile("data/grants.sqlite3") is None

def test_the_tour_leaves_a_saved_profile_as_it_was(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    mine = Profile(investigator="A. Researcher", keywords={"sleep": 12}, examples=("One.", "Two.", "Three."), focus="profile", examples_name="your example sentences")
    store = OpportunityStore("data/grants.sqlite3")
    store.save_profile(mine)
    store.close()
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.button(key="tour_start").click().run(timeout=30)
    for step in tour.TOUR_STEPS:
        _show(app, step)
    assert not app.exception and saved_profile("data/grants.sqlite3") == mine

def test_the_end_of_the_tour_puts_back_the_view_the_wizard_and_the_draft() -> None:
    draft = Profile(investigator="A. Researcher", keywords={"sleep": 12})
    for before in ({"view": "Settings"}, {"view": "Apply", "profile_step": None}, {"view": "Profile", "profile_step": 2, "profile_draft": draft, "profile_builtin": True}, {"view": "Find", "profile_step": None, "profile_draft": draft, "profile_builtin": False}):
        # The tour is closed at every step in turn, the first and the last among them.
        for closed_at in range(len(tour.TOUR_STEPS)):
            state = dict(before)
            tour.start(state)
            assert state["view"] == "Find"
            for step in tour.TOUR_STEPS[:closed_at + 1]:
                tour.show(state, step)
            tour.end(state)
            assert {key: state[key] for key in tour.KEPT if key in state} == before and "tour_back" not in state
            assert state.get("profile_draft") is before.get("profile_draft")

def test_a_tour_that_never_reported_its_end_does_not_become_the_place_to_return_to() -> None:
    state = {"view": "Settings"}
    tour.start(state)
    tour.show(state, tour.TOUR_STEPS[7])
    tour.start(state)
    tour.end(state)
    assert {key: state[key] for key in tour.KEPT if key in state} == {"view": "Settings"}
    # A second report of the end, or one with no tour open, changes nothing.
    state["view"] = "Apply"
    tour.end(state)
    assert state["view"] == "Apply"

def test_a_step_is_opened_only_while_a_tour_is_open(monkeypatch) -> None:
    from types import SimpleNamespace
    state = {"view": "Apply", "tour": SimpleNamespace(goto=6)}
    monkeypatch.setattr(tour, "st", SimpleNamespace(session_state=state))
    tour._goto()
    assert state["view"] == "Apply" and "profile_step" not in state
    tour.start(state)
    tour._goto()
    assert (state["view"], state["profile_step"]) == ("Profile", 0)
    state["tour"] = SimpleNamespace(goto=-1)
    tour._goto()
    assert state["view"] == "Apply" and "profile_step" not in state and "profile_draft" not in state

def test_the_button_is_on_every_view(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    for view in ("Find", "Apply", "Profile", "Settings"):
        app.sidebar.radio(key="view").set_value(view).run(timeout=30)
        assert not app.exception and [button.label for button in app.sidebar.button if button.key == "tour_start"] == ["Show me around"], view

def test_an_open_profile_step_is_told_that_the_tour_leaves_it(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio(key="view").set_value("Profile").run(timeout=30)
    warned = lambda: any("The tour leaves the profile step" in c.value for c in app.sidebar.caption)
    assert not warned()
    app.button(key="profile_setup").click().run(timeout=30)
    assert not app.exception and warned()

def test_a_press_on_another_view_starts_the_tour_on_find(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.radio(key="view").set_value("Settings").run(timeout=30)
    app.sidebar.button(key="tour_start").click().run(timeout=30)
    assert not app.exception and app.session_state["view"] == "Find" and app.session_state["tour_back"] == {"view": "Settings"}

def test_the_script_asks_python_for_another_view_and_reports_its_end() -> None:
    script = tour.script()
    assert "if (steps[to].place !== here) { here = steps[to].place; tour.send('goto', steps[to].at); }" in script
    assert "onNextClick: () => move(1), onPrevClick: () => move(-1)" in script
    # Closing by any way ends in onDestroyed, and a step that waits for its view does not reopen a closed tour.
    assert "if (tour.nonce === mine) tour.send('goto', -1);" in script and "if (tour.nonce !== mine) return;" in script and "await arrive(steps[to], 400) && tourDriver.isActive()" in script

def test_the_script_skips_a_step_whose_control_is_not_on_the_page() -> None:
    assert "getClientRects().length" in tour.script()

def test_the_lit_control_cannot_be_used_during_the_tour() -> None:
    # A view chosen in the lit View control would take the later steps' controls off the page.
    assert "disableActiveInteraction: true" in tour.script()

def test_show_me_around_starts_the_tour_once_for_each_press(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert "tour_nonce" not in app.session_state
    app.sidebar.button(key="tour_start").click().run(timeout=30)
    assert not app.exception
    assert app.session_state["tour_nonce"] == 1
    sent = json.loads(app.get("bidi_component")[0].proto.json)
    assert sent["nonce"] == f"{app.session_state['tour_session']}:1" and [step["key"] for step in sent["steps"]] == [step.key for step in tour.TOUR_STEPS]
    app.sidebar.button(key="tour_start").click().run(timeout=30)
    assert app.session_state["tour_nonce"] == 2

def test_the_empty_find_view_points_to_the_tour(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    assert [i.value for i in app.info] == ["Run a search or load saved results to populate the dashboard. New here? Select Show me around in the sidebar."]

def test_the_tour_waits_for_a_press_and_is_sent_its_words(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    sent = lambda: json.loads(app.get("bidi_component")[0].proto.json)
    assert sent()["nonce"] == ""
    assert [(s["key"], s["part"], s["title"], s["text"], s["place"]) for s in sent()["steps"]] == [(step.key, step.part, step.title, step.text, f"{step.view} {step.wizard}") for step in tour.TOUR_STEPS]
    app.sidebar.button(key="tour_start").click().run(timeout=30)
    first = sent()["nonce"]
    # A rerun that is not a press sends the same nonce, so the script does not start the tour again.
    app.sidebar.slider(key="find_min_score").set_value(5.0).run(timeout=30)
    assert sent()["nonce"] == first
    app.sidebar.button(key="tour_start").click().run(timeout=30)
    assert sent()["nonce"] == f"{app.session_state['tour_session']}:2" != first

def test_the_details_step_lights_the_tab_bar_and_not_the_table_under_it() -> None:
    assert {step.key: step.part for step in tour.TOUR_STEPS if step.part} == {"find_tabs": '[role="tablist"]'}
    assert "'.st-key-' + s.key + (s.part ? ' ' + s.part : '')" in tour.script()

def test_the_tour_keys_do_not_reach_macos_which_would_play_the_alert_sound() -> None:
    script = tour.script()
    # The listener goes on after drive(), because driver.js ignores a key whose keydown was prevented before its own listener ran.
    assert script.index(".drive();") < script.index("window.addEventListener('keydown', quiet)")
    assert "onDestroyed: () => { window.removeEventListener('keydown', quiet);" in script

def test_escape_and_the_arrow_keys_are_the_keys_kept_from_macos() -> None:
    assert "const quiet = e => { if (e.key === 'Escape' || e.key === 'ArrowLeft' || e.key === 'ArrowRight') e.preventDefault(); };" in tour.GLUE

def test_the_popover_takes_the_colours_of_the_app() -> None:
    assert ".driver-popover{background-color:var(--gm-tour-bg,#fff);color:var(--gm-tour-fg,#2d2d2d)" in tour.styles()
    assert "setProperty('--gm-tour-bg', c.backgroundColor)" in tour.script()

def test_a_click_outside_the_popover_still_closes_the_tour() -> None:
    # A click outside closes the tour by driver.js's default. The vendored file names the option too, so the glue is what is searched.
    assert "overlayClickBehavior" not in tour.GLUE and "overlayClickBehavior:`close`" in tour.script()

def test_the_run_search_step_names_the_section_that_holds_source() -> None:
    assert "under Source and rows." in tour.TOUR_STEPS[1].text

def test_a_view_chosen_by_hand_drops_the_place_of_a_tour_that_never_reported_its_end(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP)).run(timeout=30)
    app.sidebar.button(key="tour_start").click().run(timeout=30)
    assert "tour_back" in app.session_state
    app.sidebar.radio(key="view").set_value("Profile").run(timeout=30)
    assert not app.exception and "tour_back" not in app.session_state
