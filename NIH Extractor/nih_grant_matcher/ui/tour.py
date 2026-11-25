from __future__ import annotations
from pathlib import Path
import secrets
from typing import NamedTuple
import streamlit as st
from .profile_page import BLANK

VENDOR = Path(__file__).parent / "vendor"

# A step lights .st-key-<key>, or the element that the CSS selector part matches inside it, on the view it names. wizard is the step of the profile wizard that draws the key, and None where the wizard is closed.
class Step(NamedTuple):
    view: str
    key: str
    title: str
    text: str
    part: str = ""
    wizard: int | None = None

TOUR_STEPS: tuple[Step, ...] = (
    Step("Find", "view", "Four views", "Find ranks NIH opportunities. Apply holds the applications you write. Profile sets what the ranking looks for. Settings sets up a model to help you write. This tour visits Find, Profile and Settings, and puts you back where you started when it ends."),
    Step("Find", "find_run", "Run a search", "Run Search fetches and ranks the opportunities of the source chosen under Source and rows. A keyword narrows the search, and an empty keyword fetches everything that is open."),
    Step("Find", "find_classes", "Narrow the results", "Classification, and the two filters beside it, hide rows that are already loaded. They do not search again."),
    Step("Find", "find_table", "The results", "The highest score is first. The row you select is the one the Details tab shows."),
    Step("Find", "find_tabs", "Details", "Details shows why one opportunity matched, and Start application begins an application for it.", part='[role="tablist"]'),
    Step("Profile", "profile_setup", "Your profile", "Ranking uses a built-in profile for machine learning and data science until you save your own. This button opens five short steps that describe you and your research. The tour shows each step and saves nothing."),
    Step("Profile", "profile_wizard_0", "Step 1. You", "Choose Rank with my own research unless your field is machine learning or data science. Enter your name, or the name of your organization. Each box has a question mark that says what it is for.", wizard=0),
    Step("Profile", "profile_wizard_1", "Step 2. Your research", "Write a short summary, then three to six sentences on the aims of your work. Ranking compares each opportunity with each sentence. The next step proposes terms from this text.", wizard=1),
    Step("Profile", "profile_wizard_2", "Step 3. Your terms", "Each term adds its weight to the score of an opportunity that holds it. Remove a term that is too general, and add the words that name your field. Choose the NIH institutes that fund your field.", wizard=2),
    Step("Profile", "profile_wizard_3", "Step 4. Preview", "Preview scores the saved opportunities with your draft beside the profile in use. Go back and change the terms until the list looks right. Nothing is saved yet.", wizard=3),
    Step("Profile", "profile_wizard_4", "Step 5. What the writer reuses", "Expertise, resources and prior work do not change the ranking. The Apply view reuses them when you write an application. Save profile stores all five steps, and you can edit them later.", wizard=4),
    Step("Profile", "profile_export", "Move a profile", "Export profile downloads the profile in use as a file. To use it on another computer, paste the text of that file under Import a profile, below."),
    Step("Settings", "db_path", "The database", "One file holds your results, your profile, your applications and your settings, except an API key. Leave the path as it is unless you keep more than one."),
    Step("Settings", "apply_llm_box", "Set up a model", "A model is optional. Finding and ranking never use one. To have help with writing, choose a provider here. The section then asks for a key if the provider needs one, lists the provider's models, and asks you to agree before any of your text is sent."),
    Step("Settings", "view", "That is the tour", "Apply holds the applications you start. Start one from the Details tab under Find, with Start application. Select Show me around in the sidebar to see the tour again."),
)

GLUE = """
export default function(component) {
  const { data, setTriggerValue } = component;
  const tour = window.__grantMatcherTour || (window.__grantMatcherTour = {});
  // The page keeps one tour across reruns, and the newest mount of the component is the one that can reach Python.
  tour.send = setTriggerValue;
  if (!data.nonce || tour.nonce === data.nonce) return;
  const mine = tour.nonce = data.nonce;
  const target = s => '.st-key-' + s.key + (s.part ? ' ' + s.part : '');
  const shown = step => { const e = document.querySelector(target(step)); return !!e && e.getClientRects().length > 0; };
  const idle = () => { const a = document.querySelector('.stApp'); return !a || a.getAttribute('data-test-script-state') !== 'running'; };
  // Resolves true as soon as the step's control is on the page, and false once the app has finished a run without it or 10 seconds have passed.
  const arrive = (step, least) => new Promise(done => { const began = Date.now(); let calm = 0; const look = () => { const waited = Date.now() - began; if (step && shown(step)) return done(true); calm = idle() ? calm + 1 : 0; if ((calm > 2 && waited >= least) || waited > 10000) return done(false); setTimeout(look, 50); }; look(); });
  const quiet = e => { if (e.key === 'Escape' || e.key === 'ArrowLeft' || e.key === 'ArrowRight') e.preventDefault(); };
  // Python sets the view before this run, so the first view's controls are drawn by the time the app is idle.
  arrive(null, 0).then(() => {
    // A second press before this tour drew starts its own, and driver.js ends the older one, whose end must not reach Python as the end of the newer.
    if (tour.nonce !== mine) return;
    const steps = data.steps.map((s, at) => ({ ...s, at })).filter(s => s.place !== data.steps[0].place || shown(s));
    const app = document.querySelector('.stApp');
    if (app) { const c = getComputedStyle(app); document.documentElement.style.setProperty('--gm-tour-bg', c.backgroundColor); document.documentElement.style.setProperty('--gm-tour-fg', c.color); }
    let here = steps[0].place, moving = false;
    // A step in another place asks Python to draw that place, then waits for its control. A control that never comes is passed over in the direction of travel.
    const move = async by => {
      if (moving) return;
      moving = true;
      for (let to = tourDriver.getActiveIndex() + by; to >= 0 && tourDriver.isActive(); to += by) {
        if (to >= steps.length) { tourDriver.destroy(); break; }
        if (steps[to].place !== here) { here = steps[to].place; tour.send('goto', steps[to].at); }
        if (await arrive(steps[to], 400) && tourDriver.isActive()) { tourDriver.moveTo(to); break; }
      }
      moving = false;
    };
    // A keydown that no page script prevents goes back to macOS, which beeps. driver.js acts on keyup and ignores a key whose keydown was prevented before its own bubbling keydown listener, so this one is added after drive().
    const tourDriver = lib.driver({ showProgress: true, disableActiveInteraction: true, onNextClick: () => move(1), onPrevClick: () => move(-1), onDestroyed: () => { window.removeEventListener('keydown', quiet); if (tour.nonce === mine) tour.send('goto', -1); }, steps: steps.map(s => ({ element: target(s), popover: { title: s.title, description: s.text } })) });
    tourDriver.drive();
    window.addEventListener('keydown', quiet);
  });
}
"""

# The script copies the app's background and text colours into these two variables, so the popover follows the Streamlit theme, light or dark.
THEME = (".driver-popover{background-color:var(--gm-tour-bg,#fff);color:var(--gm-tour-fg,#2d2d2d);border:1px solid color-mix(in srgb,var(--gm-tour-fg,#2d2d2d) 25%,transparent)}"
    ".driver-popover-footer-btn{background-color:var(--gm-tour-bg,#fff);color:var(--gm-tour-fg,#2d2d2d);border-color:color-mix(in srgb,var(--gm-tour-fg,#2d2d2d) 40%,transparent);text-shadow:none}"
    ".driver-popover-footer-btn:hover,.driver-popover-footer-btn:focus-visible{background-color:color-mix(in srgb,var(--gm-tour-fg,#2d2d2d) 12%,var(--gm-tour-bg,#fff))}"
    ".driver-popover-close-btn{color:color-mix(in srgb,var(--gm-tour-fg,#2d2d2d) 60%,var(--gm-tour-bg,#fff))}.driver-popover-close-btn:hover,.driver-popover-close-btn:focus-visible{color:var(--gm-tour-fg,#2d2d2d)}"
    ".driver-popover-progress-text{color:color-mix(in srgb,var(--gm-tour-fg,#2d2d2d) 70%,var(--gm-tour-bg,#fff))}"
    ".driver-popover-arrow-side-left{border-left-color:var(--gm-tour-bg,#fff)}.driver-popover-arrow-side-right{border-right-color:var(--gm-tour-bg,#fff)}"
    ".driver-popover-arrow-side-top{border-top-color:var(--gm-tour-bg,#fff)}.driver-popover-arrow-side-bottom{border-bottom-color:var(--gm-tour-bg,#fff)}\n")

def styles() -> str:
    # Streamlit's sidebar sits at z-index 999991 and driver.js puts its overlay at 10000, so the overlay is raised above it.
    return "/* driver.js 1.14.0, MIT licence, see driver.js.LICENSE */\n" + (VENDOR / "driver.css").read_text(encoding="utf-8") + "\n.driver-overlay{z-index:1000000!important}\n" + THEME

def script() -> str:
    # The vendored file assigns to this.driver, and this is undefined at the top of a module.
    return "// driver.js 1.14.0, MIT licence, see driver.js.LICENSE\nconst lib = (function(){" + (VENDOR / "driver.js.iife.js").read_text(encoding="utf-8") + "; return this.driver.js; }).call({});\n" + GLUE

# isolate_styles=False, because driver.js adds its popover to the page body, outside any shadow root.
_tour = st.components.v2.component("grant_matcher_tour", js=script(), css=styles(), isolate_styles=False)

# What a tour changes to show a view, and so what its end puts back.
KEPT = ("view", "profile_step", "profile_draft", "profile_builtin")

def show(state, step: Step) -> None:
    state["view"] = step.view
    if step.view == "Profile":
        state["profile_step"] = step.wizard
        # The wizard reads a draft, and a tour that opens it for a user who has none shows the empty one.
        if step.wizard is not None and "profile_draft" not in state:
            state["profile_draft"] = BLANK

def start(state) -> None:
    state["tour_nonce"] = state.get("tour_nonce", 0) + 1
    # A tour that never reported its end leaves its own view behind, so the place to return to is the one kept first.
    state.setdefault("tour_back", {key: state[key] for key in KEPT if key in state})
    show(state, TOUR_STEPS[0])

def end(state) -> None:
    back = state.pop("tour_back", None)
    if back is None:
        return
    for key in KEPT:
        state.pop(key, None)
    state.update(back)

def _goto() -> None:
    to = st.session_state["tour"].goto
    if "tour_back" in st.session_state and isinstance(to, int) and to < len(TOUR_STEPS):
        end(st.session_state) if to < 0 else show(st.session_state, TOUR_STEPS[to])

def tour_button() -> None:
    st.button("Show me around", key="tour_start", on_click=start, args=(st.session_state,), width="stretch")
    # A form's unsubmitted values live in the browser only, and the tour leaves the form.
    if st.session_state.get("view") == "Profile" and st.session_state.get("profile_step") is not None and "tour_back" not in st.session_state:
        st.caption("The tour leaves the profile step you are on. Text you typed in the step since you opened it is lost.")
    # The script ignores the nonce it started last, so a rerun does not restart the tour, and the session's name keeps a new server's count from matching the one an old tab saw.
    session, presses = st.session_state.setdefault("tour_session", secrets.token_hex(4)), st.session_state.get("tour_nonce", 0)
    _tour(data={"nonce": f"{session}:{presses}" if presses else "", "steps": [{"key": s.key, "part": s.part, "title": s.title, "text": s.text, "place": f"{s.view} {s.wizard}"} for s in TOUR_STEPS]}, key="tour", on_goto_change=_goto)
