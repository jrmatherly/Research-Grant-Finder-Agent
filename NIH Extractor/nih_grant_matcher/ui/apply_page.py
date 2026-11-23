from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Callable
import streamlit as st
from ..announcement import SECTION_TITLES
from ..clients import ApiError
from ..models import Finding, Opportunity
from ..rules import FACT_KINDS
from ..store import OpportunityStore
from ..writer import NotReady, StaleEdit, Workspace, describe
from .profile_page import escape_markdown

ACKNOWLEDGE = "A model drafted or revised most of this section's words. I have rewritten what I needed to, and it states my own ideas."
HOW_TO_START = "No application yet. To start one, open an opportunity under Details in the Find view and choose Start application."
STATUS = {None: "Not yet decided.", True: "Confirmed.", False: "Rejected."}

def _notice(kind: str, text: str) -> None:
    st.session_state["apply_notices"] = [*st.session_state.get("apply_notices", []), (kind, text)]

def _findings(findings: tuple[Finding, ...]) -> str:
    return " ".join(escape_markdown(f.message) for f in findings)

def _act(db_path: str, action: Callable[[OpportunityStore], str | None]) -> None:
    # A callback runs before the page is drawn, so its outcome waits in session state for the page to show.
    store = None
    try:
        store = OpportunityStore(db_path)
        done = action(store)
    except NotReady as exc:
        _notice("error", f"{escape_markdown(exc.reason)} {_findings(exc.findings)}".strip())
    except ApiError as exc:
        _notice("error", f"{escape_markdown(str(exc))} The standing rules of the grant type still apply.")
    except (sqlite3.Error, ValueError, OSError) as exc:
        _notice("error", escape_markdown(str(exc)))
    else:
        if done:
            _notice("success", done)
    finally:
        if store is not None:
            store.close()

def _on(db_path: str, app_id: int, action: Callable[[Workspace], str | None]) -> None:
    def run(store: OpportunityStore) -> str | None:
        try:
            return action(Workspace(store, app_id))
        except StaleEdit as exc:
            # The Sections tab shows both texts for this section, which says more than the message.
            st.session_state["apply_stale"] = (app_id, exc.head.section)
            return None
    _act(db_path, run)

def _open_first_tab() -> None:
    st.session_state["apply_tabs_opened"] = st.session_state.get("apply_tabs_opened", 0) + 1

def start_application(db_path: str, opportunity: Opportunity, grant_type: str, resubmission: bool) -> None:
    def start(store: OpportunityStore) -> None:
        st.session_state["application_id"] = Workspace.start(store, opportunity, grant_type, resubmission).application_id
    _act(db_path, start)
    _open_first_tab()
    # A widget's key may be set only in a callback, which runs before the radio is drawn again.
    st.session_state["view"] = "Apply"

def _keys(app_id: int, section: str) -> tuple[str, str]:
    return f"apply_text_{app_id}_{section}", f"apply_base_{app_id}_{section}"

def _save(ws: Workspace, section: str, title: str) -> str:
    text_key, base_key = _keys(ws.application_id, section)
    base = st.session_state.get(base_key)
    revision = ws.write(section, st.session_state.get(text_key, ""), base)
    st.session_state[base_key] = revision.id
    st.session_state.pop("apply_stale", None)
    return f"Nothing changed since revision {revision.id}." if revision.id == base else f"Saved revision {revision.id} of the {title}."

def _sign(ws: Workspace, section: str, title: str) -> str:
    text_key, base_key = _keys(ws.application_id, section)
    base = st.session_state.get(base_key)
    shown = next((r for r in ws.store.revisions(ws.application_id) if r.id == base), None)
    if shown is not None and shown.text != st.session_state.get(text_key, ""):
        raise NotReady("Save your text before you sign off. A sign-off covers the revision you saved.")
    signed = ws.sign(section, st.session_state.get("apply_signer", ""), base or 0, st.session_state.get(f"apply_acknowledge_{ws.application_id}_{section}", False))
    return f"Signed off the {title} at revision {signed.revision_id}."

def _restore(ws: Workspace, section: str, revision_id: int) -> str:
    restored = ws.restore(section, revision_id)
    text_key, base_key = _keys(ws.application_id, section)
    st.session_state[text_key], st.session_state[base_key] = restored.text, restored.id
    return f"Restored the text of revision {revision_id} as revision {restored.id}."

def _add_fact(ws: Workspace) -> str:
    fact = ws.add_fact(st.session_state.get("apply_fact_kind", "other"), st.session_state.get("apply_fact_text", ""), st.session_state.get("apply_fact_label", ""))
    st.session_state["apply_fact_text"] = st.session_state["apply_fact_label"] = ""
    return f"Added input {fact.id} under {fact.kind}."

def owned_by(app_id: int, key: str) -> bool:
    # The parts are split at underscores, so id 1 does not match id 11, and a section key holds no underscore.
    return key.startswith("apply_") and not key.endswith("_button") and str(app_id) in key.split("_")[2:]

def _delete(ws: Workspace, number: str) -> str:
    if st.session_state.get(f"apply_delete_{ws.application_id}", "").strip() != number:
        raise ValueError(f"Type {number} to delete this application. Nothing was deleted.")
    ws.delete()
    # Ids are reused after a delete, so every value keyed by this id goes with it.
    for key in [k for k in st.session_state if owned_by(ws.application_id, str(k))] + ["application_id", "apply_stale"]:
        st.session_state.pop(key, None)
    _open_first_tab()
    return f"Deleted the application for {escape_markdown(number)} and everything logged for it."

def apply_page(db_path: str) -> None:
    st.header("Apply")
    # The frontend matches the tabs by their place on the page, so a notice that came and went would reopen the first tab. Each container holds its place whether or not it has a notice.
    with st.container():
        for kind, text in st.session_state.pop("apply_notices", []):
            getattr(st, kind)(text)
    # Opening a store creates the file, so a path with no database yet has no application either.
    if not Path(db_path).exists():
        st.info(HOW_TO_START)
        return
    store = None
    try:
        store = OpportunityStore(db_path)
        _page(store, db_path)
    except (sqlite3.Error, ValueError) as exc:
        st.error(escape_markdown(str(exc)))
    finally:
        if store is not None:
            store.close()

def _page(store: OpportunityStore, db_path: str) -> None:
    apps = store.applications()
    if not apps:
        st.info(HOW_TO_START)
        return
    ids = [a.id for a in apps]
    if st.session_state.get("application_id") not in ids:
        st.session_state["application_id"] = ids[-1]
    labels = {a.id: f"{a.opportunity_number} as {a.grant_type.split(':')[-1]}{', a resubmission' if a.resubmission else ''}. {a.title}" for a in apps}
    app_id = st.selectbox("Application", ids, format_func=labels.__getitem__, key="application_id")
    path = str(store.db_path)
    st.caption(f"Your text, your inputs and every model call for this application are stored in {f'`{path}`' if '`' not in path else escape_markdown(path)}. Anyone who can read that file can read them.")
    ws = Workspace(store, app_id)
    view = ws.view()
    with st.container():
        for notice in view.notices:
            st.warning(notice)
    # The open tab is the browser's and follows the key, so a tab click needs no rerun. A start or a delete changes the key, which opens the first tab.
    announcement_tab, requirements_tab, inputs_tab, sections_tab, log_tab = st.tabs(["Announcement", "Requirements", "Your inputs", "Sections", "Log and export"], key=f"apply_tabs_{st.session_state.get('apply_tabs_opened', 0)}")
    with announcement_tab:
        st.button("Fetch the full announcement", key="apply_fetch_button", type="primary", on_click=_on, args=(db_path, app_id, lambda w: f"Saved the announcement from {'the NIH Guide' if w.fetch_announcement().origin == 'nih-guide' else 'Grants.gov'}. Confirm or reject what it adds under Requirements."))
        a = view.announcement
        if a is None:
            st.info("The announcement has not been fetched yet. The standing rules of the grant type apply until it is.")
        else:
            st.caption(f"Fetched from {'the NIH Guide' if a.origin == 'nih-guide' else 'Grants.gov'} on {a.fetched_at:%Y-%m-%d}.")
            st.link_button("Open the announcement", a.url, key="apply_announcement_button")
            parts = [(f"Section {n}. {SECTION_TITLES[n]}", a.section(n)) for n in ("I", "IV", "V") if a.section(n)]
            for title, text in parts or [("Full text", a.text)]:
                with st.expander(title):
                    st.text(text)
    with requirements_tab:
        st.subheader("Standing rules")
        st.caption(f"NIH sets these for every {view.grant_type.code} application unless the announcement says otherwise.")
        for s in view.sections:
            st.markdown(f"**{s.rule.title}**. At most {describe(s.rule.limit)}." + (f" You confirmed the announcement's limit of {describe(s.limit)}." if s.limit != s.rule.limit else ""))
        for source in view.grant_type.sources:
            st.caption(f"[{source.url}]({source.url}), read on {source.read_on}. {source.says}")
        st.subheader("What the announcement adds")
        if not view.requirements:
            st.info("Fetch the full announcement to see what it adds." if a is None else "Grant Matcher found no added requirement in the announcement. Read Section IV under Announcement.")
        for r in view.requirements:
            st.markdown(f"**{escape_markdown(r.text)}** {STATUS[r.confirmed]}")
            st.text(r.quote)
            confirm, reject = st.columns(2)
            confirm.button("Confirm", key=f"apply_confirm_{r.id}_button", disabled=r.confirmed is True, on_click=_on, args=(db_path, app_id, lambda w, rid=r.id: w.decide(rid, True)))
            reject.button("Reject", key=f"apply_reject_{r.id}_button", disabled=r.confirmed is False, on_click=_on, args=(db_path, app_id, lambda w, rid=r.id: w.decide(rid, False)))
    with inputs_tab:
        for s in view.sections:
            if s.gaps:
                st.caption(f"The {s.rule.title} still needs {', '.join(s.gaps)}.")
        st.caption("A retired input stays in the log and no longer counts in the checks.")
        for kind in FACT_KINDS:
            st.markdown(f"**{kind.capitalize()}**")
            facts = [f for f in view.facts if f.kind == kind]
            if not facts:
                st.caption("None yet.")
            for f in facts:
                text, retire = st.columns([6, 1])
                text.markdown(escape_markdown((f"[@{f.label}] " if f.label else "") + f.text))
                retire.button("Retire", key=f"apply_retire_{f.id}_button", on_click=_on, args=(db_path, app_id, lambda w, fid=f.id: w.retire_fact(fid)))
        with st.form("apply_fact_form"):
            st.selectbox("Kind", FACT_KINDS, key="apply_fact_kind")
            st.text_input("Key", key="apply_fact_label", help="For a reference, the key that a section cites as [@key]. Letters, digits and hyphens.")
            st.text_area("Text", key="apply_fact_text")
            st.form_submit_button("Add input", key="apply_add_fact_button", on_click=_on, args=(db_path, app_id, _add_fact))
    with sections_tab:
        keys = [s.rule.key for s in view.sections]
        if st.session_state.get("apply_section") not in keys:
            st.session_state["apply_section"] = keys[0]
        key = st.selectbox("Section", keys, format_func=lambda k: view.section(k).rule.title, key="apply_section")
        s = view.section(key)
        text_key, base_key = _keys(app_id, key)
        shown = next((r for r in view.log if r.id == st.session_state.get(base_key)), None)
        # Text the applicant has not changed follows the newest revision, and changed text stays until Save.
        if text_key not in st.session_state or (st.session_state.get(base_key) != s.revision_id and (shown.text if shown else "") == st.session_state[text_key]):
            st.session_state[text_key], st.session_state[base_key] = s.text, s.revision_id
        st.caption(f"{s.rule.title}. At most {describe(s.limit)}. " + {"empty": "No text saved yet.", "draft": f"Draft at revision {s.revision_id}.", "final": f"Signed off at revision {s.revision_id}."}[s.state])
        if s.gaps:
            st.info(f"This section still needs {', '.join(s.gaps)}. Add them under Your inputs.")
        if st.session_state.get("apply_stale") == (app_id, key):
            st.warning("This section changed after you opened it, so your text was not saved. The newest revision and your text are below. Copy what you need, then load the newest revision.")
            newest, yours = st.columns(2)
            newest.caption(f"Revision {s.revision_id}")
            newest.text(s.text)
            yours.caption("Your text")
            yours.text(st.session_state[text_key])
            st.button("Load the newest revision", key="apply_load_newest_button", on_click=_load_newest, args=(text_key, base_key, s.text, s.revision_id))
        with st.form("apply_section_form"):
            st.text_area(s.rule.title, key=text_key, height=360)
            st.form_submit_button("Save", key="apply_save_button", type="primary", on_click=_on, args=(db_path, app_id, lambda w, key=key, title=s.rule.title: _save(w, key, title)))
            if "apply_signer" not in st.session_state:
                st.session_state["apply_signer"] = _investigator(store)
            st.text_input("Your name", key="apply_signer")
            if any(f.code == "mostly-drafted" for f in s.findings):
                st.checkbox(ACKNOWLEDGE, key=f"apply_acknowledge_{app_id}_{key}")
            st.form_submit_button("Sign off", key="apply_sign_button", on_click=_on, args=(db_path, app_id, lambda w, key=key, title=s.rule.title: _sign(w, key, title)))
        words = s.attribution
        st.caption(f"You wrote {round(100 * words.applicant_words / (words.applicant_words + words.model_words or 1))}% of the words. A model drafted or revised {round(100 * words.written_share)}%, and a model polished {round(100 * words.polished_share)}%.")
        for f in s.findings:
            (st.error if f.severity == "error" else st.warning)(escape_markdown(f.message) + (f"\n\n_{escape_markdown(f.excerpt)}_" if f.excerpt else ""))
        if s.revision_id is not None and not s.findings:
            st.success(f"The checks found nothing to fix in revision {s.revision_id}.")
    with log_tab:
        st.subheader("Revisions")
        titles, heads = {s.rule.key: s.rule.title for s in view.sections}, {s.revision_id for s in view.sections}
        if not view.log:
            st.caption("No revisions yet.")
        for r in reversed(view.log):
            line, restore = st.columns([6, 1])
            line.markdown(f"Revision {r.id}. {titles.get(r.section, r.section)}. " + ("You wrote it" if r.author == "applicant" else f"A model's {r.action}") + f" on {r.created_at:%Y-%m-%d at %H:%M} UTC. {len(r.text.split())} words.")
            restore.button("Restore", key=f"apply_restore_{r.id}_button", disabled=r.id in heads, on_click=_on, args=(db_path, app_id, lambda w, section=r.section, rid=r.id: _restore(w, section, rid)))
        st.subheader("Export")
        export_key = f"apply_export_{app_id}"
        if export_key not in st.session_state:
            st.session_state[export_key] = f"outputs/application-{app_id}"
        st.text_input("Export folder", key=export_key, help="One Markdown file per section, the requirements and the provenance log. A section that is not signed off starts with DRAFT-.")
        st.button("Export", key="apply_export_button", on_click=_on, args=(db_path, app_id, lambda w, export_key=export_key: f"Wrote the application to {escape_markdown(str(w.export(Path(st.session_state[export_key]))))}."))
        st.subheader("Delete this application")
        number = view.application.opportunity_number
        st.caption("Delete removes this application with its text, its inputs, its sign-offs and every model call logged for it. It cannot be undone.")
        typed = st.text_input(f"Type {escape_markdown(number)} to confirm", key=f"apply_delete_{app_id}")
        st.button("Delete this application", key="apply_delete_button", disabled=typed.strip() != number, on_click=_on, args=(db_path, app_id, lambda w, number=number: _delete(w, number)))

def _load_newest(text_key: str, base_key: str, text: str, revision_id: int | None) -> None:
    st.session_state[text_key], st.session_state[base_key] = text, revision_id
    st.session_state.pop("apply_stale", None)

def _investigator(store: OpportunityStore) -> str:
    try:
        return store.profile().investigator
    except ValueError:
        return ""
