from __future__ import annotations
from pathlib import Path
import secrets
import streamlit as st

VENDOR = Path(__file__).parent / "vendor"

TOUR_STEPS: tuple[tuple[str, str, str], ...] = (
    ("view", "Four views", "Find ranks NIH opportunities. Apply holds the applications you write. Profile sets what the ranking looks for. Settings sets up a model to help you write."),
    ("find_run", "Run a search", "Choose a source, add a keyword if you want one, and select Run Search. Leave the keyword empty to see everything that is open."),
    ("find_classes", "Narrow the results", "Classification, and the two filters beside it, hide rows that are already loaded. They do not search again."),
    ("find_table", "The results", "The highest score is first. Select a row to choose it for the Details tab."),
    ("find_tabs", "Details", "Details shows why one opportunity matched, and Start application begins an application for it."),
    ("", "That is the tour", "Select Show me around in the sidebar to see it again."),
)

GLUE = """
export default function(component) {
  const { data } = component;
  if (!data.nonce || window.__grantMatcherTour === data.nonce) return;
  window.__grantMatcherTour = data.nonce;
  const shown = step => { if (!step.key) return true; const e = document.querySelector('.st-key-' + step.key); return !!e && e.getClientRects().length > 0; };
  const steps = data.steps.filter(shown).map(s => ({ element: s.key ? '.st-key-' + s.key : undefined, popover: { title: s.title, description: s.text } }));
  lib.driver({ showProgress: true, disableActiveInteraction: true, steps }).drive();
}
"""

def styles() -> str:
    # Streamlit's sidebar sits at z-index 999991 and driver.js puts its overlay at 10000, so the overlay is raised above it.
    return "/* driver.js 1.14.0, MIT licence, see driver.js.LICENSE */\n" + (VENDOR / "driver.css").read_text(encoding="utf-8") + "\n.driver-overlay{z-index:1000000!important}\n"

def script() -> str:
    # The vendored file assigns to this.driver, and this is undefined at the top of a module.
    return "// driver.js 1.14.0, MIT licence, see driver.js.LICENSE\nconst lib = (function(){" + (VENDOR / "driver.js.iife.js").read_text(encoding="utf-8") + "; return this.driver.js; }).call({});\n" + GLUE

# isolate_styles=False, because driver.js adds its popover to the page body, outside any shadow root.
_tour = st.components.v2.component("grant_matcher_tour", js=script(), css=styles(), isolate_styles=False)

def _start() -> None:
    st.session_state["tour_nonce"] = st.session_state.get("tour_nonce", 0) + 1

def tour_button() -> None:
    st.button("Show me around", key="tour_start", on_click=_start, width="stretch")
    # The script starts the tour only for a nonce it has not seen, so a rerun does not restart it.
    # The count starts again in a new session, and a tab that outlives its server keeps the last press it saw, so each session has its own name.
    session, presses = st.session_state.setdefault("tour_session", secrets.token_hex(4)), st.session_state.get("tour_nonce", 0)
    _tour(data={"nonce": f"{session}:{presses}" if presses else "", "steps": [{"key": k, "title": t, "text": x} for k, t, x in TOUR_STEPS]}, key="tour")
