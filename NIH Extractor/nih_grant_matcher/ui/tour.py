from __future__ import annotations
from pathlib import Path
import secrets
import streamlit as st

VENDOR = Path(__file__).parent / "vendor"

# (key, part, title, text): the step lights .st-key-<key>, or the element that the CSS selector part matches inside it.
TOUR_STEPS: tuple[tuple[str, str, str, str], ...] = (
    ("view", "", "Four views", "Find ranks NIH opportunities. Apply holds the applications you write. Profile sets what the ranking looks for. Settings sets up a model to help you write."),
    ("find_run", "", "Run a search", "Run Search fetches and ranks the opportunities of the source chosen under Source and rows. A keyword narrows the search, and an empty keyword fetches everything that is open."),
    ("find_classes", "", "Narrow the results", "Classification, and the two filters beside it, hide rows that are already loaded. They do not search again."),
    ("find_table", "", "The results", "The highest score is first. The row you select is the one the Details tab shows."),
    ("find_tabs", '[role="tablist"]', "Details", "Details shows why one opportunity matched, and Start application begins an application for it."),
    ("", "", "That is the tour", "Select Show me around in the sidebar to see it again."),
)

GLUE = """
export default function(component) {
  const { data } = component;
  if (!data.nonce || window.__grantMatcherTour === data.nonce) return;
  window.__grantMatcherTour = data.nonce;
  const target = s => '.st-key-' + s.key + (s.part ? ' ' + s.part : '');
  const shown = step => { if (!step.key) return true; const e = document.querySelector(target(step)); return !!e && e.getClientRects().length > 0; };
  const steps = data.steps.filter(shown).map(s => ({ element: s.key ? target(s) : undefined, popover: { title: s.title, description: s.text } }));
  if (!steps.some(s => s.element)) console.error('Grant Matcher tour: no control matched .st-key-<key>.');
  const app = document.querySelector('.stApp');
  if (app) { const c = getComputedStyle(app); document.documentElement.style.setProperty('--gm-tour-bg', c.backgroundColor); document.documentElement.style.setProperty('--gm-tour-fg', c.color); }
  // A keydown that no page script prevents goes back to macOS, which beeps. driver.js acts on keyup and ignores a key whose keydown was prevented before its own bubbling keydown listener, so this one is added after drive().
  const quiet = e => { if (e.key === 'Escape' || e.key === 'ArrowLeft' || e.key === 'ArrowRight') e.preventDefault(); };
  lib.driver({ showProgress: true, disableActiveInteraction: true, onDestroyed: () => window.removeEventListener('keydown', quiet), steps }).drive();
  window.addEventListener('keydown', quiet);
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

def _start() -> None:
    st.session_state["tour_nonce"] = st.session_state.get("tour_nonce", 0) + 1

def tour_button() -> None:
    st.button("Show me around", key="tour_start", on_click=_start, width="stretch")
    # The script ignores the nonce it started last, so a rerun does not restart the tour, and the session's name keeps a new server's count from matching the one an old tab saw.
    session, presses = st.session_state.setdefault("tour_session", secrets.token_hex(4)), st.session_state.get("tour_nonce", 0)
    _tour(data={"nonce": f"{session}:{presses}" if presses else "", "steps": [{"key": k, "part": p, "title": t, "text": x} for k, p, t, x in TOUR_STEPS]}, key="tour")
