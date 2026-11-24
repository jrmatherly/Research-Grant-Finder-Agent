from __future__ import annotations
import os
import sqlite3
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable
import streamlit as st
from .. import keys
from ..announcement import SECTION_TITLES
from ..clients import ApiError
from ..llm import PROVIDERS, cautions, checked_base_url, checked_workspace, chosen, connect, host_of, list_models, missing, workspace
from ..models import Finding, Opportunity
from ..provenance import percent
from ..rules import FACT_KINDS
from ..store import OpportunityStore
from ..writer import DECISIONS, DROPPED, NO_SECTION_IV, ORIGINS, STALE_PROPOSAL, ApplicationView, NotReady, StaleEdit, Workspace, describe, dropped_points, lookup_line, read_summary, score_line
from .markdown import escape_markdown

ACKNOWLEDGE = "A model drafted or revised most of this section's words. I have rewritten what I needed to, and it states my own ideas."
HOW_TO_START = "No application yet. To start one, open an opportunity under Details in the Find view and choose Start application. A model is optional, and you set one up under Settings."
ACTION_NOUNS = {"revise": "revision"}
POINT_LABELS = {"strength": "Strength", "weakness": "Weakness", "prose": "Writing"}
PROVIDER_LABELS = {"claude": "Claude, from Anthropic", "openai": "OpenAI", "gemini": "Gemini, from Google", "compatible": "A server that speaks the OpenAI API, such as Ollama"}

def _notice(kind: str, text: str) -> None:
    st.session_state["apply_notices"] = [*st.session_state.get("apply_notices", []), (kind, text)]

def _findings(findings: tuple[Finding, ...]) -> str:
    return " ".join(escape_markdown(f.message) for f in findings)

def show_notices() -> None:
    for kind, text in st.session_state.pop("apply_notices", []):
        getattr(st, kind)(text)

def _act(db_path: str, action: Callable[[OpportunityStore], str | None]) -> bool:
    # A callback runs before the page is drawn, so its outcome waits in session state for the page to show.
    store = None
    try:
        store = OpportunityStore(db_path)
        done = action(store)
    except NotReady as exc:
        _notice("error", f"{escape_markdown(exc.reason)} {_findings(exc.findings)}".strip())
    except (ApiError, keys.UnreadableKey, sqlite3.Error, ValueError, OSError) as exc:
        _notice("error", escape_markdown(str(exc)))
    else:
        if done:
            _notice("success", done)
        return True
    finally:
        if store is not None:
            store.close()
    return False

def _on(db_path: str, app_id: int, action: Callable[[Workspace], str | None], stale: str = "save") -> None:
    def run(store: OpportunityStore) -> str | None:
        try:
            return action(Workspace(store, app_id))
        except StaleEdit as exc:
            # Restore is pressed on the Log and export tab, so its refusal goes above the tabs. For a save or a sign-off the Sections tab shows both texts, which says more.
            if stale == "restore":
                _notice("warning", "This section changed in another tab, so nothing was restored. The page now shows the current text.")
            else:
                st.session_state["apply_stale"] = (app_id, exc.head.section, stale)
            return None
    _act(db_path, run)

def _open_first_tab() -> None:
    st.session_state["apply_tabs_opened"] = st.session_state.get("apply_tabs_opened", 0) + 1

def start_application(db_path: str, opportunity: Opportunity, grant_type: str, resubmission: bool) -> None:
    def start(store: OpportunityStore) -> None:
        st.session_state["application_id"] = Workspace.start(store, opportunity, grant_type, resubmission).application_id
    # A refused start leaves the Find view, which shows the error under the button.
    if _act(db_path, start):
        _open_first_tab()
        # The radio is already drawn in the run that shows this button, so its key can change only here, in the callback.
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
    signed = ws.sign(section, st.session_state.get("apply_signer", ""), base or 0, st.session_state.get(f"apply_acknowledge_{ws.application_id}_{section}_{base}", False))
    return f"Signed off the {title} at revision {signed.revision_id}."

def _fetch(ws: Workspace) -> str:
    try:
        announcement, notes = ws.fetch_announcement()
    except ApiError as exc:
        raise ApiError(f"{exc} " + ("The announcement saved earlier still applies, with what you decided from it." if ws.view().announcement else "The standing rules of the grant type still apply.")) from exc
    return f"Saved the announcement from {ORIGINS[announcement.origin]}. " + (NO_SECTION_IV if ws.view().no_section_iv else "Confirm or reject what it adds under Requirements.") + "".join(" " + escape_markdown(note) for note in notes)

def _restore(ws: Workspace, section: str, revision_id: int, parent: int | None) -> str:
    restored = ws.restore(section, revision_id, parent)
    text_key, base_key = _keys(ws.application_id, section)
    st.session_state[text_key], st.session_state[base_key] = restored.text, restored.id
    return f"Restored the text of revision {revision_id} as revision {restored.id}."

def _add_fact(ws: Workspace) -> str:
    fact = ws.add_fact(st.session_state.get("apply_fact_kind", "other"), st.session_state.get("apply_fact_text", ""), st.session_state.get("apply_fact_label", ""))
    st.session_state["apply_fact_text"] = st.session_state["apply_fact_label"] = ""
    return f"Added input {fact.id} under {fact.kind}."

def _verify(ws: Workspace) -> str:
    checked = ws.verify_references()
    return f"Checked {checked} reference{'' if checked == 1 else 's'} with PubMed or Crossref. The result is under each reference."

def _propose(ws: Workspace, section: str, action: str, instruction: str = "") -> str:
    ws.model = connect(ws.store)
    ws.propose(section, action, instruction)
    return "The model's proposal is below the section. Nothing has changed yet."

def _review(ws: Workspace, section: str) -> str | None:
    ws.model = connect(ws.store)
    review = ws.review(section)
    # Another tab can save while the model reads, and a review is shown only beside the revision it read.
    if review.revision_id != ws.view().section(section).revision_id:
        _notice("warning", f"The section changed while the model was reading it, so this review is of revision {review.revision_id}, an earlier one, and is not shown. Review the section again.")
        return None
    return f"The model reviewed revision {review.revision_id}. Its review is below the section."

def _extract(ws: Workspace) -> str:
    ws.model = connect(ws.store)
    found, dropped = ws.extract_requirements()
    return f"{read_summary(found)} Confirm or reject each under Requirements." + (f" Grant Matcher dropped {dropped} item{'' if dropped == 1 else 's'} of the model's replies. {DROPPED}" if dropped else "")

def _accept(ws: Workspace, call_id: int, edited: str | None) -> str:
    try:
        revision = ws.accept(call_id, edited)
    except StaleEdit:
        if any(r.call_id == call_id for r in ws.store.revisions(ws.application_id)):
            raise NotReady(f"Proposal {call_id} was already accepted, so your edits were not saved. The section shows the accepted text.") from None
        raise NotReady(STALE_PROPOSAL) from None
    return f"Accepted the proposal as revision {revision.id}."

def _discard(ws: Workspace, call_id: int) -> str:
    ws.discard(call_id)
    return "Discarded the proposal. It stays in the log."

def _and(names: list[str]) -> str:
    return f"{', '.join(names[:-1])} and {names[-1]}" if len(names) > 1 else names[0]

def _word_diff(old: str, new: str) -> str:
    a, b, parts = old.split(), new.split(), []
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag == "equal":
            parts.append(escape_markdown(" ".join(a[i1:i2])))
        if tag in ("delete", "replace"):
            parts.append(f"~~{escape_markdown(' '.join(a[i1:i2]))}~~")
        if tag in ("insert", "replace"):
            parts.append(f"**{escape_markdown(' '.join(b[j1:j2]))}**")
    return " ".join(parts)

def owned_by(app_id: int, key: str) -> bool:
    # Every key of an application holds its id third, as in apply_edit_{app}_{section}_{call}, and a section key holds no underscore.
    return key.startswith("apply_") and not key.endswith("_button") and key.split("_")[2:3] == [str(app_id)]

def _delete(ws: Workspace, number: str) -> str:
    if st.session_state.get(f"apply_delete_{ws.application_id}", "").strip() != number:
        raise ValueError(f"Type {number} to delete this application. Nothing was deleted.")
    ws.delete()
    # Every value keyed by this id goes with it, so the session holds nothing of an application that is gone.
    for key in [k for k in st.session_state if owned_by(ws.application_id, str(k))] + ["application_id", "apply_stale"]:
        st.session_state.pop(key, None)
    _open_first_tab()
    return f"Deleted the application for {escape_markdown(number)} and everything logged for it."

def apply_page(db_path: str) -> None:
    st.header("Apply")
    # The frontend matches the tabs by their place on the page, so a notice that came and went would reopen the first tab. Each container holds its place whether or not it has a notice.
    with st.container():
        show_notices()
    # Opening a store creates the file, so a path with no database yet has no application either.
    store = None
    try:
        if not os.path.exists(db_path):
            st.info(HOW_TO_START)
            return
        store = OpportunityStore(db_path)
        _page(store, db_path)
    except (sqlite3.Error, OSError) as exc:
        st.error(database_error(db_path, exc))
    except ValueError as exc:
        st.error(escape_markdown(str(exc)))
    finally:
        if store is not None:
            store.close()

def database_error(db_path: str, exc: Exception) -> str:
    return escape_markdown(f"Could not open the database at {db_path}: {exc}. Check the Database path in the sidebar, and that no other program has the file open.")

def _page(store: OpportunityStore, db_path: str) -> None:
    apps = store.applications()
    if not apps:
        st.info(HOW_TO_START)
        return
    ids = [a.id for a in apps]
    if st.session_state.get("application_id") not in ids:
        st.session_state["application_id"] = ids[-1]
    labels = {a.id: f"{a.opportunity_number} as {a.grant_type.split(':')[-1]}{', a resubmission' if a.resubmission else ''}. {a.title}" for a in apps}
    app_id = st.selectbox("Application", ids, format_func=labels.__getitem__, key="application_id", persist_state="session")
    path = str(store.db_path)
    st.caption(f"Your text, your inputs and every model call for this application are stored in {f'`{path}`' if '`' not in path else escape_markdown(path)}. Anyone who can read that file can read them.")
    model_settings(store, db_path)
    try:
        model = connect(store)
    except (keys.UnreadableKey, OSError):
        # The Model section above already shows why the key cannot be read.
        model = None
    ws = Workspace(store, app_id, model)
    view = ws.view()
    with st.container():
        for notice in view.notices:
            st.warning(notice)
    # The open tab is the browser's and follows the key, so a tab click needs no rerun. A start or a delete changes the key, which opens the first tab.
    announcement_tab, requirements_tab, inputs_tab, sections_tab, log_tab = st.tabs(["Announcement", "Requirements", "Your inputs", "Sections", "Log and export"], key=f"apply_tabs_{st.session_state.get('apply_tabs_opened', 0)}")
    with announcement_tab:
        _announcement_tab(view, db_path, app_id)
    with requirements_tab:
        _requirements_tab(view, ws, db_path, app_id)
    with inputs_tab:
        _inputs_tab(view, db_path, app_id)
    with sections_tab:
        _sections_tab(view, ws, db_path, app_id)
    with log_tab:
        _log_tab(view, db_path, app_id)

def model_settings(store: OpportunityStore, db_path: str, expanded: bool | None = None) -> None:
    picked = chosen(store)
    with st.expander("Model", expanded=expanded if expanded is not None else not (picked and picked[1] and store.setting(f"consent:{host_of(picked[2])}"))):
        st.caption("A model can help you write. Grant Matcher sends your text to the provider you choose here and to no one else.")
        # The boxes below are seeded once, so another database starts them again from its own record.
        if st.session_state.get("apply_llm_db", db_path) != db_path:
            for key in ("apply_llm_model", "apply_llm_base_url", "apply_llm_workspace", "apply_llm_models"):
                st.session_state.pop(key, None)
        st.session_state["apply_llm_db"] = db_path
        # The provider comes from the record on every run, so a choice that was not saved does not stay shown.
        st.session_state["apply_llm_provider"] = picked[0].name if picked else None
        st.selectbox("Provider", list(PROVIDERS), format_func=PROVIDER_LABELS.__getitem__, placeholder="Choose a provider", key="apply_llm_provider", persist_state="session", on_change=_act, args=(db_path, _choose_provider))
        if picked is None:
            return
        provider, name, base_url = picked
        if provider.name == "compatible":
            if "apply_llm_base_url" not in st.session_state:
                st.session_state["apply_llm_base_url"] = base_url
            st.text_input("Base URL", key="apply_llm_base_url", persist_state="session", help="The address of the server's OpenAI API, such as http://localhost:11434/v1 for Ollama.", on_change=_act, args=(db_path, lambda s: s.set_setting("llm.base_url", checked_base_url(st.session_state["apply_llm_base_url"]))))
        if provider.name == "claude":
            if "apply_llm_workspace" not in st.session_state:
                st.session_state["apply_llm_workspace"] = workspace(store)
            st.text_input("Workspace ID", key="apply_llm_workspace", persist_state="session", placeholder="wrkspc_...", help="Only for a key that is not scoped to one workspace, such as a personal key made for every workspace you can use. The Workspaces page of the Claude Console, platform.claude.com/settings/workspaces, lists each ID. Leave it empty for a key made for one workspace.", on_change=_act, args=(db_path, lambda s: s.set_setting("llm.workspace", checked_workspace(st.session_state["apply_llm_workspace"]))))
        try:
            key = keys.get(provider, store.db_path.parent)
        except (keys.UnreadableKey, OSError) as exc:
            st.error(escape_markdown(str(exc)))
            # The error is kept so that a rerun does not ask the Keychain again, so a new attempt waits for this button.
            st.button("Try again", key="apply_llm_retry_button", on_click=keys.forget)
            return
        where = keys.where(provider, store.db_path.parent)
        # The last four characters of a short key are most of it.
        st.caption(f"{escape_markdown(where)}, ends in ...{escape_markdown(key[-4:])}." if key and len(key) >= 12 and where.startswith("Saved") else f"{escape_markdown(where)}." if key else "No key saved." + ("" if provider.needs_key else " This provider does not need one."))
        if keys.PLATFORM == "win32":
            st.caption("On Windows the key file is protected by your user account only.")
        with st.form("apply_llm_key_form"):
            # The key does not persist, because Save clears it and a persisted value would send the secret back to the browser.
            st.text_input("API key", type="password", key="apply_llm_key", help=f"Saved in the macOS Keychain on a Mac, and in a file beside the database elsewhere. {provider.key_env} or {provider.key_env}_FILE, when set, wins over a saved key.")
            st.form_submit_button("Save key", key="apply_llm_save_key_button", on_click=_act, args=(db_path, _save_key))
        if key and where.startswith("Saved"):
            st.button("Remove the saved key", key="apply_llm_remove_key_button", on_click=_act, args=(db_path, _remove_key))
        listed = st.session_state.get("apply_llm_models", {}).get(provider.name, [])
        if "apply_llm_model" not in st.session_state:
            st.session_state["apply_llm_model"] = name or None
        st.selectbox("Model", list(dict.fromkeys([*([name] if name else []), *listed])), placeholder="List the provider's models to choose one", key="apply_llm_model", persist_state="session", on_change=_act, args=(db_path, lambda s: s.set_setting("llm.model", st.session_state["apply_llm_model"] or "")))
        st.button("List the provider's models", key="apply_llm_list_button", on_click=_act, args=(db_path, _list_models))
        host = host_of(base_url)
        st.caption(f"Your text goes to {escape_markdown(host)}.")
        for caution in cautions(provider, base_url):
            st.warning(escape_markdown(caution))
        agreed, consent_key = bool(store.setting(f"consent:{host}")), f"apply_llm_consent_{host}"
        # Streamlit unticks a box on the run that turns disabled on, whatever value says, so the box takes its state from the record on every run.
        st.session_state[consent_key] = agreed
        # A label is its accessible name as written and renders an IPv6 or www. host as an emoji or a link whatever the escape, so the host stays in the caption above.
        st.checkbox("I agree to send my text to this host", disabled=agreed, key=consent_key, on_change=_act, args=(db_path, lambda s, host=host: s.set_setting(f"consent:{host}", datetime.now(timezone.utc).replace(tzinfo=None).isoformat())))
        st.button("Test connection", key="apply_llm_test_button", disabled=not agreed, help="Sends one short request, which the provider may charge for.", on_click=_act, args=(db_path, _test_connection))

def _choose_provider(store: OpportunityStore) -> None:
    store.set_setting("llm.provider", st.session_state["apply_llm_provider"])
    # A new provider starts from its own default model. The Base URL and Workspace ID boxes are redrawn from what is saved.
    store.set_setting("llm.model", "")
    for key in ("apply_llm_model", "apply_llm_base_url", "apply_llm_workspace"):
        st.session_state.pop(key, None)

def _save_key(store: OpportunityStore) -> str:
    key, st.session_state["apply_llm_key"] = st.session_state.get("apply_llm_key", "").strip(), ""
    return f"Saved the key in {escape_markdown(keys.save(chosen(store)[0], key, store.db_path.parent))}."

def _remove_key(store: OpportunityStore) -> str:
    keys.delete(chosen(store)[0], store.db_path.parent)
    return "Removed the saved key."

def _list_models(store: OpportunityStore) -> str:
    provider, _, base_url = chosen(store)
    found = list_models(provider, base_url, keys.get(provider, store.db_path.parent), workspace(store))
    st.session_state["apply_llm_models"] = {**st.session_state.get("apply_llm_models", {}), provider.name: found}
    return f"{escape_markdown(host_of(base_url))} lists {len(found)} model{'' if len(found) == 1 else 's'}."

def _test_connection(store: OpportunityStore) -> str:
    model = connect(store)
    if model is None:
        raise ValueError("Choose a model, and save a key if the provider needs one, before you test the connection.")
    # The Base URL's callback runs first when it is edited and the button clicked at once, so the disabled button is not enough.
    if not store.setting(f"consent:{model.host}"):
        raise ValueError(f"Agree to send text to {model.host} first.")
    done = model.complete("Answer in one word.", "Say hello.", max_tokens=64)
    return f"{escape_markdown(done.model)} at {escape_markdown(model.host)} answered. The test used {done.input_tokens + done.output_tokens} tokens."

def _announcement_tab(view: ApplicationView, db_path: str, app_id: int) -> None:
    st.button("Fetch the full announcement", key="apply_fetch_button", type="primary", on_click=_on, args=(db_path, app_id, _fetch))
    a = view.announcement
    if a is None:
        st.info("The announcement has not been fetched yet. The standing rules of the grant type apply until it is.")
    else:
        st.caption(f"Fetched from {ORIGINS[a.origin]} on {a.fetched_at:%Y-%m-%d}." + (" That service drops some brackets and spaces of the notice and joins a heading to the next word, so read a quote against the announcement. Fetch again for the notice's own text." if a.origin == "nih-guide" else ""))
        st.link_button("Open the announcement", a.url, key="apply_announcement_button")
        if view.no_section_iv:
            st.info(NO_SECTION_IV)
        parts = [(f"Section {n}. {SECTION_TITLES[n]}", a.section(n)) for n in ("I", "IV", "V") if a.section(n)]
        for title, text in parts or [("Full text", a.text)]:
            with st.expander(title):
                st.text(text)

def _requirements_tab(view: ApplicationView, ws: Workspace, db_path: str, app_id: int) -> None:
    st.subheader("Standing rules")
    st.caption(f"NIH sets these for every {view.grant_type.code} application unless the announcement says otherwise.")
    for s in view.sections:
        st.markdown(f"**{s.rule.title}**. At most {describe(s.rule.limit)}." + (f" You confirmed the announcement's limit of {describe(s.limit)}." if s.limit != s.rule.limit else ""))
    for source in view.grant_type.sources:
        st.caption(f"[{source.url}]({source.url}), read on {source.read_on}. {source.says}")
    st.subheader("What the announcement adds")
    if ws.model is not None:
        st.caption(f"A model can read Sections I, IV and V and list what they ask for, each with the words of the announcement it comes from. The text goes to {escape_markdown(ws.model.host)}, and nothing counts until you confirm it.")
    else:
        st.caption(f"Reading the announcement needs a model. {_missing(ws.store)} Set it up under Model at the top of this page.")
    st.button("Ask the model to read the announcement", key="apply_extract_button", disabled=ws.model is None or view.announcement is None, help="Set up a model under Model first." if ws.model is None else "Fetch the announcement under Announcement first." if view.announcement is None else None, on_click=_on, args=(db_path, app_id, _extract))
    if view.no_section_iv:
        st.info(NO_SECTION_IV)
    elif not view.requirements:
        st.info("Fetch the full announcement to see what it adds." if view.announcement is None else "Grant Matcher found no added requirement in the announcement. Read Section IV under Announcement.")
    for r in view.requirements:
        st.markdown(f"**{escape_markdown(r.text)}** {DECISIONS[r.confirmed].capitalize()}." + (f" At most {describe(r.limit)}." if r.limit else "") + (" A model read this." if r.origin == "model" else ""))
        st.text(r.quote)
        confirm, reject = st.columns(2)
        confirm.button("Confirm", key=f"apply_confirm_{r.id}_button", disabled=r.confirmed is True, on_click=_on, args=(db_path, app_id, lambda w, rid=r.id: w.decide(rid, True)))
        reject.button("Reject", key=f"apply_reject_{r.id}_button", disabled=r.confirmed is False, on_click=_on, args=(db_path, app_id, lambda w, rid=r.id: w.decide(rid, False)))

def _inputs_tab(view: ApplicationView, db_path: str, app_id: int) -> None:
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
            if kind == "reference":
                text.caption(escape_markdown(lookup_line(f)))
            retire.button("Retire", key=f"apply_retire_{f.id}_button", on_click=_on, args=(db_path, app_id, lambda w, fid=f.id: w.retire_fact(fid)))
        if kind == "reference" and facts:
            st.caption("A model can invent a reference. This check sends the PMID of each reference to NCBI (PubMed), or its DOI to Crossref when it has no PMID. The request carries that identifier and this tool's name, and none of your text. No model is involved. Compare the title each index holds with the reference you typed.")
            st.button("Check that each reference exists", key="apply_verify_button", on_click=_on, args=(db_path, app_id, _verify))
    with st.form("apply_fact_form"):
        st.selectbox("Kind", FACT_KINDS, key="apply_fact_kind", persist_state="session")
        st.text_input("Key", key="apply_fact_label", persist_state="session", help="For a reference, the key that a section cites as [@key]. Letters, digits and hyphens.")
        st.text_area("Text", key="apply_fact_text", persist_state="session")
        st.form_submit_button("Add input", key="apply_add_fact_button", on_click=_on, args=(db_path, app_id, _add_fact))

def _sections_tab(view: ApplicationView, ws: Workspace, db_path: str, app_id: int) -> None:
    keys = [s.rule.key for s in view.sections]
    if st.session_state.get("apply_section") not in keys:
        st.session_state["apply_section"] = keys[0]
    key = st.selectbox("Section", keys, format_func=lambda k: view.section(k).rule.title, key="apply_section", persist_state="session")
    s = view.section(key)
    text_key, base_key = _keys(app_id, key)
    shown = next((r for r in view.log if r.id == st.session_state.get(base_key)), None)
    # Text the applicant has not changed follows the newest revision, and changed text stays until Save.
    if text_key not in st.session_state or (st.session_state.get(base_key) != s.revision_id and (shown.text if shown else "") == st.session_state[text_key]):
        st.session_state[text_key], st.session_state[base_key] = s.text, s.revision_id
    st.caption(f"{s.rule.title}. At most {describe(s.limit)}. " + {"empty": "No text saved yet.", "draft": f"Draft at revision {s.revision_id}.", "final": f"Signed off at revision {s.revision_id}."}[s.state])
    if s.gaps:
        st.info(f"This section still needs {', '.join(s.gaps)}. Add {'it' if len(s.gaps) == 1 else 'them'} under Your inputs.")
    if (stale := st.session_state.get("apply_stale")) and stale[:2] == (app_id, key):
        st.warning({"sign": "This section changed since this page loaded, so nothing was signed. The newest revision and your text are below. Read the newest revision before you sign off."}.get(stale[2], "This section changed after you opened it, so your text was not saved. The newest revision and your text are below. Copy what you need, then load the newest revision."))
        newest, yours = st.columns(2)
        newest.caption(f"Revision {s.revision_id}")
        newest.text(s.text)
        yours.caption("Your text")
        yours.text(st.session_state[text_key])
        st.button("Load the newest revision", key="apply_load_newest_button", on_click=_load_newest, args=(text_key, base_key, s.text, s.revision_id))
    with st.form("apply_section_form"):
        # A widget drawn again after a run without it shows its default, not the value the server kept, unless it persists, so each Apply widget that holds typed or chosen state persists, except the API key and the consent box.
        st.text_area(s.rule.title, key=text_key, height=360, persist_state="session")
        st.form_submit_button("Save", key="apply_save_button", type="primary", on_click=_on, args=(db_path, app_id, lambda w, key=key, title=s.rule.title: _save(w, key, title)))
        if "apply_signer" not in st.session_state:
            st.session_state["apply_signer"] = _investigator(ws.store)
        st.text_input("Your name", key="apply_signer", persist_state="session")
        if any(f.code == "mostly-drafted" for f in s.findings):
            # An acknowledgement is of one revision, so a new revision draws a new, unticked box.
            st.checkbox(ACKNOWLEDGE, key=f"apply_acknowledge_{app_id}_{key}_{s.revision_id}", persist_state="session")
        st.form_submit_button("Sign off", key="apply_sign_button", on_click=_on, args=(db_path, app_id, lambda w, key=key, title=s.rule.title: _sign(w, key, title), "sign"))
    # Review reads only the saved text, so every section offers it, and the section's rule says which of the others a model may do.
    edits = ["Polish", "Revise"] if s.rule.model != "none" else []
    if ws.model is not None:
        st.caption(f"{_and([*edits, 'Review'])} send{'' if edits else 's'} the saved revision to {escape_markdown(ws.model.host)}" + (", and Draft sends your inputs for it" if s.rule.model == "draft" else "") + ". " + ("A proposal changes nothing until you accept it, and a review changes nothing." if edits else "A review changes nothing."))
    else:
        actions = [*(["Draft"] if s.rule.model == "draft" else []), *edits, "Review"]
        st.caption(f"{_and(actions)} need{'' if len(actions) > 1 else 's'} a model. {_missing(ws.store)} Set it up under Model at the top of this page.")
    if ws.model is not None and s.rule.model != "none":
        instruction_key = f"apply_instruction_{app_id}_{key}"
        st.text_input("What to change", key=instruction_key, persist_state="session", help="Revise needs this. For example: Make the second aim shorter.")
        polish, revise = st.columns(2)
        polish.button("Polish", key="apply_polish_button", disabled=s.revision_id is None, on_click=_on, args=(db_path, app_id, lambda w, key=key: _propose(w, key, "polish")))
        revise.button("Revise", key="apply_revise_button", disabled=s.revision_id is None, on_click=_on, args=(db_path, app_id, lambda w, key=key, instruction_key=instruction_key: _propose(w, key, "revise", st.session_state.get(instruction_key, ""))))
        if s.rule.model == "draft":
            st.button("Draft from my inputs", key="apply_draft_button", disabled=bool(s.gaps), help=f"Add {', '.join(s.gaps)} under Your inputs first." if s.gaps else f"Sends your inputs for this section, the requirements you confirmed for it, and the research summary and expertise in your profile to {escape_markdown(ws.model.host)}.", on_click=_on, args=(db_path, app_id, lambda w, key=key: _propose(w, key, "draft")))
    if ws.model is not None:
        st.button("Review against NIH criteria", key="apply_review_button", disabled=not s.text.strip(), help=f"Sends only the saved revision and the review criteria you confirmed to {escape_markdown(ws.model.host)}. The model scores it as a reviewer would, and the section does not change.", on_click=_on, args=(db_path, app_id, lambda w, key=key: _review(w, key)))
    # A proposal waits in the log, so a reload shows it again.
    if (proposal := ws.pending(key)) is not None:
        st.markdown(f"**A model's {ACTION_NOUNS.get(proposal.action, proposal.action)}, proposal {proposal.call_id}**")
        current, proposed = st.columns(2)
        current.caption(f"Revision {s.revision_id}" if s.revision_id is not None else "The section has no text yet.")
        current.text(s.text)
        proposed.caption("Struck words go and bold words come in.")
        proposed.markdown(_word_diff(s.text, proposal.text))
        for f in proposal.findings:
            (st.error if f.severity == "error" else st.warning)(escape_markdown(f.message) + (f"\n\n_{escape_markdown(f.excerpt)}_" if f.excerpt else ""))
        edit_key = f"apply_edit_{app_id}_{key}_{proposal.call_id}"
        if edit_key not in st.session_state:
            st.session_state[edit_key] = proposal.text
        st.text_area("Your edits to the proposal", key=edit_key, persist_state="session", help="Change the proposal here, then choose Accept with my edits. Your changed words count as yours.")
        accept, mine, discard = st.columns(3)
        accept.button("Accept", key="apply_accept_button", type="primary", on_click=_on, args=(db_path, app_id, lambda w, call_id=proposal.call_id: _accept(w, call_id, None)))
        mine.button("Accept with my edits", key="apply_accept_edited_button", on_click=_on, args=(db_path, app_id, lambda w, call_id=proposal.call_id, edit_key=edit_key: _accept(w, call_id, st.session_state.get(edit_key))))
        discard.button("Discard", key="apply_discard_button", on_click=_on, args=(db_path, app_id, lambda w, call_id=proposal.call_id: _discard(w, call_id)))
    if (review := s.review) is not None:
        factors = view.grant_type.factors
        st.markdown(f"**A model's review of revision {review.revision_id}**")
        st.caption(f"{escape_markdown(review.model)} saw only this revision and the review criteria you confirmed. NIH's reviewers score the whole application.")
        for factor in factors:
            st.markdown(escape_markdown(score_line(factor, review.scores.get(factor.key))))
        titles = {f.key: f.title for f in factors}
        for point in review.points:
            st.markdown(f"**{POINT_LABELS[point.kind]}**{f' ({titles[point.factor]})' if point.factor else ''}. {escape_markdown(point.text)}")
            st.text(point.quote)
        if review.dropped:
            st.caption(dropped_points(review))
    words = s.attribution
    st.caption(f"You wrote {percent(words.applicant_words / (words.applicant_words + words.model_words or 1))} of the words. A model drafted or revised {percent(words.written_share)}, and a model polished {percent(words.polished_share)}.")
    for f in s.findings:
        (st.error if f.severity == "error" else st.warning)(escape_markdown(f.message) + (f"\n\n_{escape_markdown(f.excerpt)}_" if f.excerpt else ""))
    if s.revision_id is not None and not s.findings:
        if s.text.strip():
            st.success(f"The checks found nothing to fix in revision {s.revision_id}.")
        else:
            st.info("No text saved yet.")

def _log_tab(view: ApplicationView, db_path: str, app_id: int) -> None:
    st.subheader("Revisions")
    titles, heads = {s.rule.key: s.rule.title for s in view.sections}, {s.rule.key: s.revision_id for s in view.sections}
    if not view.log:
        st.caption("No revisions yet.")
    for r in reversed(view.log):
        line, restore = st.columns([6, 1])
        line.markdown(f"Revision {r.id}. {titles.get(r.section, r.section)}. " + ("You wrote it" if r.author == "applicant" else f"A model's {ACTION_NOUNS.get(r.action, r.action)}") + f" on {r.created_at:%Y-%m-%d at %H:%M} UTC. {len(r.text.split())} words.")
        restore.button("Restore", key=f"apply_restore_{r.id}_button", disabled=r.id in heads.values(), on_click=_on, args=(db_path, app_id, lambda w, section=r.section, rid=r.id, parent=heads.get(r.section): _restore(w, section, rid, parent), "restore"))
    st.subheader("AI-use statement")
    st.caption("Grant Matcher builds this statement from the log, one sentence for each thing the log holds, with no model. NIH names no field for it, so the export writes it to ai-use-statement.md for you to place.")
    disclosure_key = f"apply_disclosure_{app_id}"
    if disclosure_key not in st.session_state:
        st.session_state[disclosure_key] = view.application.disclosure_on
    st.toggle("Include the statement in the export", key=disclosure_key, persist_state="session", on_change=_on, args=(db_path, app_id, lambda w, disclosure_key=disclosure_key: w.set_disclosure(st.session_state[disclosure_key])))
    if view.disclosure:
        st.markdown(escape_markdown(view.disclosure))
    st.subheader("Export")
    export_key = f"apply_export_{app_id}"
    if export_key not in st.session_state:
        st.session_state[export_key] = f"outputs/application-{app_id}"
    st.text_input("Export folder", key=export_key, persist_state="session", help="One Markdown file per section, the requirements, the provenance log and, while it is on, the AI-use statement. A section that is not signed off starts with DRAFT-.")
    st.button("Export", key="apply_export_button", on_click=_on, args=(db_path, app_id, lambda w, export_key=export_key: f"Wrote the application to {escape_markdown(str(w.export(Path(st.session_state[export_key]))))}."))
    st.subheader("Delete this application")
    number = view.application.opportunity_number
    st.caption(f"Delete removes this application with its text, its inputs, its sign-offs, its reviews and every model call logged for it. It cannot be undone. Files you exported stay where you exported them. To delete it, type {escape_markdown(number)} below.")
    typed = st.text_input("Type the opportunity number to confirm", key=f"apply_delete_{app_id}", persist_state="session")
    st.button("Delete this application", key="apply_delete_button", disabled=typed.strip() != number, on_click=_on, args=(db_path, app_id, lambda w, number=number: _delete(w, number)))

def _missing(store: OpportunityStore) -> str:
    try:
        return missing(store) or ""
    except (keys.UnreadableKey, OSError):
        return "The key cannot be read."

def _load_newest(text_key: str, base_key: str, text: str, revision_id: int | None) -> None:
    st.session_state[text_key], st.session_state[base_key] = text, revision_id
    st.session_state.pop("apply_stale", None)

def _investigator(store: OpportunityStore) -> str:
    try:
        return store.profile().investigator
    except ValueError:
        return ""
