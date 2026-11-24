import hashlib
import json
from pathlib import Path
from streamlit.testing.v1 import AppTest
from nih_grant_matcher.ui import tour

APP = Path(__file__).resolve().parents[1] / "streamlit_app.py"
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

def test_every_step_points_at_a_key_the_find_view_draws() -> None:
    text = APP.read_text(encoding="utf-8")
    keys = [key for key, _, _, _ in tour.TOUR_STEPS if key]
    assert keys == ["view", "find_run", "find_classes", "find_table", "find_tabs"]
    assert all(f'key="{key}"' in text for key in keys)
    assert tour.TOUR_STEPS[-1][0] == ""

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
    assert sent["nonce"] == f"{app.session_state['tour_session']}:1" and [step["key"] for step in sent["steps"]] == [key for key, _, _, _ in tour.TOUR_STEPS]
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
    assert [(s["key"], s["part"], s["title"], s["text"]) for s in sent()["steps"]] == list(tour.TOUR_STEPS)
    app.sidebar.button(key="tour_start").click().run(timeout=30)
    first = sent()["nonce"]
    # A rerun that is not a press sends the same nonce, so the script does not start the tour again.
    app.sidebar.slider(key="find_min_score").set_value(5.0).run(timeout=30)
    assert sent()["nonce"] == first
    app.sidebar.button(key="tour_start").click().run(timeout=30)
    assert sent()["nonce"] == f"{app.session_state['tour_session']}:2" != first

def test_the_details_step_lights_the_tab_bar_and_not_the_table_under_it() -> None:
    assert {key: part for key, part, _, _ in tour.TOUR_STEPS if part} == {"find_tabs": '[role="tablist"]'}
    assert "'.st-key-' + s.key + (s.part ? ' ' + s.part : '')" in tour.script()

def test_the_tour_keys_do_not_reach_macos_which_would_play_the_alert_sound() -> None:
    script = tour.script()
    # The listener goes on after drive(), because driver.js ignores a key whose keydown was prevented before its own listener ran.
    assert script.index(".drive();") < script.index("window.addEventListener('keydown', quiet)")
    assert "onDestroyed: () => window.removeEventListener('keydown', quiet)" in script

def test_escape_and_the_arrow_keys_are_the_keys_kept_from_macos() -> None:
    assert "const quiet = e => { if (e.key === 'Escape' || e.key === 'ArrowLeft' || e.key === 'ArrowRight') e.preventDefault(); };" in tour.GLUE

def test_the_popover_takes_the_colours_of_the_app() -> None:
    assert ".driver-popover{background-color:var(--gm-tour-bg,#fff);color:var(--gm-tour-fg,#2d2d2d)" in tour.styles()
    assert "setProperty('--gm-tour-bg', c.backgroundColor)" in tour.script()

def test_a_click_outside_the_popover_still_closes_the_tour() -> None:
    # A click outside closes the tour by driver.js's default. The vendored file names the option too, so the glue is what is searched.
    assert "overlayClickBehavior" not in tour.GLUE and "overlayClickBehavior:`close`" in tour.script()

def test_the_run_search_step_names_the_section_that_holds_source() -> None:
    assert "under Source and rows." in tour.TOUR_STEPS[1][3]
