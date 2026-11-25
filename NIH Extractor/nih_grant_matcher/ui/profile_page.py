from __future__ import annotations
import os
import re, sqlite3
from dataclasses import replace
from pathlib import Path
import pandas as pd
import streamlit as st
from ..config import INSTITUTE_BONUS, INSTITUTES
from ..profile import BUILTIN_PROFILE, MAX_CITATION, MAX_INSTITUTES, MAX_KEYWORD, MAX_SENTENCE, TEXT_LIMITS, Profile, ProfileError, Reference, from_export, ranks_like_builtin, suggest_terms, to_export
from ..scoring import MLRelevanceScorer
from ..store import OpportunityStore
from ..workflow import config_for
from .markdown import escape_markdown

STEPS = ("You", "Your research", "Your terms", "Preview", "What the writer reuses")
CAREER_STAGES = ("early-stage investigator", "new investigator", "established")
RANKINGS = ("Rank with my own research", "Keep the built-in ranking")
BLANK = Profile(keywords={}, examples=(), focus="profile", examples_name="your example sentences")

def saved_profile(db_path: str) -> Profile | None:
    # Opening a store creates the file, and the Find view loads any file it finds, so read only one that exists.
    if not os.path.exists(db_path):
        return None
    store = OpportunityStore(db_path)
    try:
        profile = store.profile()
    finally:
        store.close()
    # Equality ignores the order of the keywords, and the order is the order of matched_terms.
    return None if to_export(profile) == to_export(BUILTIN_PROFILE) else profile

def profile_sentence(profile: Profile) -> str:
    name = escape_markdown(profile.investigator)
    if ranks_like_builtin(profile):
        return "Ranking uses the built-in profile (machine learning and data science) " + (f"for {name}." if name else "with your background.")
    return f"Ranking uses the profile of {name or 'an unnamed investigator'}, with {len(profile.keywords)} terms and {len(profile.examples)} example sentences."

def show_unreadable(exc: ProfileError) -> None:
    st.error(f"The saved profile cannot be read, so ranking uses the built-in profile. Reset to built-in under Profile deletes the saved profile, and the database file holds its only copy. {escape_markdown(str(exc))}")

def _apply(db_path: str, make, done: str) -> None:
    try:
        profile = make()
        store = OpportunityStore(db_path)
        try:
            store.save_profile(profile)
        finally:
            store.close()
    except (ProfileError, sqlite3.Error) as exc:
        st.session_state["profile_notice"] = ("error", escape_markdown(str(exc)))
        return
    st.session_state["profile_notice"] = ("success", done)
    st.session_state["profile_step"] = None
    st.session_state["scored_items"] = []

def read_terms(terms: pd.DataFrame) -> tuple[dict[str, int], list[str], list[tuple[str, str, int]]]:
    # The scorer matches lower-case text, and a saved profile refuses any other term.
    keywords: dict[str, int] = {}
    dropped, first, pairs = [], {}, []
    for term, weight in zip(terms["Term"], terms["Weight"]):
        if pd.isna(term) or not str(term).strip():
            continue
        if pd.isna(weight):
            dropped.append(str(term).strip())
            continue
        name = str(term).strip()
        if name.lower() in first:
            pairs.append((first[name.lower()], name))
        first.setdefault(name.lower(), name)
        keywords[name.lower()] = int(weight)
    return keywords, dropped, [(a, b, keywords[a.lower()]) for a, b in pairs]

def _preview(db_path: str, draft: Profile) -> pd.DataFrame | None:
    if not os.path.exists(db_path):
        return None
    store = OpportunityStore(db_path)
    try:
        current, opportunities = MLRelevanceScorer(config_for(store)), [item.opportunity for item in store.top_scored(limit=-1)]
    finally:
        store.close()
    proposed = MLRelevanceScorer(draft.matcher_config())
    rows = []
    for opp in opportunities:
        before, after = current.score(opp), proposed.score(opp)
        rows.append({"Opportunity Number": opp.opportunity_number, "Title": opp.title, "Current Score": before.score, "Draft Score": after.score, "Change": round(after.score - before.score, 1), "Why It Matched": "; ".join(after.reasons)})
    rows.sort(key=lambda row: -row["Change"])
    return pd.DataFrame([row for row in rows if row["Change"] > 0][:10] + [row for row in reversed(rows) if row["Change"] < 0][:10][::-1]) if rows else None

# Streamlit cuts a value longer than max_chars without a word, so text saved over a limit before the limits existed is shown whole and the save names the field.
def _limit(name: str, draft: Profile) -> int | None:
    return TEXT_LIMITS[name] if len(getattr(draft, name)) <= TEXT_LIMITS[name] else None

def _step(n: int, db_path: str, draft: Profile) -> None:
    st.subheader(f"{n + 1}. {STEPS[n]}")
    with st.form(f"profile_step_{n}"):
        if n == 0:
            ranking = st.radio("Ranking", RANKINGS, index=int(st.session_state.get("profile_builtin", False)), help="Rank with my own research builds the ranking from the sentences and terms you enter in steps 2 and 3. Keep the built-in ranking keeps the terms for machine learning and data science and skips steps 2 to 4.")
            investigator = st.text_input("Name", value=draft.investigator, max_chars=_limit("investigator", draft), placeholder="Jane Doe, PhD", help="Your name, or the name of your organization when the organization is the applicant. It names the profile on the Find and Profile views, and the Apply view offers it as the name that signs off a section. Ranking does not read it.")
            institution = st.text_input("Institution", value=draft.institution, max_chars=_limit("institution", draft), placeholder="Example State University, Department of Public Health", help="Where you work. An organization that applies in its own name can repeat that name or leave this empty. It is kept with the profile and in an exported file. Ranking and drafting do not read it.")
            stage = st.selectbox("Career stage", CAREER_STAGES, index=CAREER_STAGES.index(draft.career_stage) if draft.career_stage in CAREER_STAGES else None, placeholder="Choose a stage", help="Where the principal investigator is in a research career. An organization leaves it empty. It is kept with the profile and in an exported file. Ranking and drafting do not read it.")
        elif n == 1:
            summary = st.text_area("Research summary", value=draft.research_summary, max_chars=_limit("research_summary", draft), placeholder="We study [the problem] in [the people, place or system], using [your methods], so that [the benefit to health].", help="A paragraph on what you study and why it matters. Step 3 proposes terms from it, and a model reads it when it drafts a section under Apply. Ranking does not compare opportunities with it.")
            aims = st.text_area("Aims of recent or planned work", value="\n".join(draft.examples), placeholder="Aim 1 will test whether [the intervention or exposure] changes [the outcome] in [the population].\nAim 2 will find [the mechanism or the barriers] behind that change.\nAim 3 will build and evaluate [the tool, method or program] for [the setting].", help="Three to six sentences, as a paragraph or one per line. Ranking compares each opportunity with each sentence.")
        elif n == 2:
            st.caption("Terms proposed from your research text. Keep, remove, re-weight or add terms. A weight runs from 1 to 30.")
            st.caption("An opportunity gains the weight of each term its title or text holds, and more for a term in the title. A phrase is one term. Example row: Term `patient outcomes`, Weight `12`.")
            # A frame with no rows types Term as a number, and the editor refuses a text column over numbers.
            terms = st.data_editor(pd.DataFrame({"Term": list(draft.keywords), "Weight": list(draft.keywords.values())}, columns=["Term", "Weight"]).astype({"Term": str}), num_rows="dynamic", hide_index=True, width="stretch", column_config={"Term": st.column_config.TextColumn("Term", max_chars=MAX_KEYWORD), "Weight": st.column_config.NumberColumn("Weight", min_value=1, max_value=30, step=1, default=10)})
            institutes = st.multiselect("Your NIH institutes", list(INSTITUTES), default=draft.institutes, format_func=lambda code: f"{code}, {INSTITUTES[code]}", max_selections=MAX_INSTITUTES, help="The institutes that issue most of the opportunities in your field. Leave it empty when you are not sure, and no record gets the bonus.")
            st.caption(f"A record issued by one of these institutes gets {INSTITUTE_BONUS:g} points. Choose up to three. It helps most when one institute funds your field. A record issued by NIH for several institutes gets no bonus.")
        elif n == 3:
            st.caption("Check the ranking before you save. A rise should be an opportunity you want to read. When the list looks wrong, go Back and change your sentences or your terms.")
            preview = _preview(db_path, draft)
            if preview is None:
                st.info("No saved opportunities to preview. Run a search under Find first.")
            elif preview.empty:
                st.info("Your draft scores every saved opportunity the same as the current profile.")
            else:
                st.caption("The ten largest rises and the ten largest falls among the saved opportunities, scored with your draft beside the current profile. Nothing is saved yet.")
                st.dataframe(preview, width="stretch", hide_index=True)
        else:
            expertise = st.text_area("Expertise", value=draft.expertise, max_chars=_limit("expertise", draft), placeholder="[Number] years of [your methods] in [your field]. Led [number] studies of [the topic]. The team includes [the roles and skills].", help="What qualifies you or your team for the work. A model reads it when it drafts a section under Apply, and a number here is not flagged as one a model invented. Ranking does not read it.")
            resources = st.text_area("Resources", value=draft.resources, max_chars=_limit("resources", draft), placeholder="Access to [the facility, core or clinic]. A data set of [number] [records or samples]. A partnership with [the laboratory, health system or community group].", help="The facilities, equipment, data and partners you can use. No model reads it. A draft is checked against it, so a number here is not flagged as one a model invented. Ranking does not read it.")
            st.caption("Prior work, one reference per row. A key holds only letters, digits and hyphens.")
            st.caption("Each application you start begins with these references, and a section cites one as [@key]. Example row: Key `author2024`, Citation `Author A, Author B. Title of the paper. Journal Name. 2024;12(3):45-67.`, PMID `12345678`, DOI `10.1000/example`.")
            refs = st.data_editor(pd.DataFrame([{"Key": ref.key, "Citation": ref.citation, "PMID": ref.pmid, "DOI": ref.doi} for ref in draft.prior_work], columns=["Key", "Citation", "PMID", "DOI"], dtype=str), num_rows="dynamic", hide_index=True, width="stretch", column_config={"Citation": st.column_config.TextColumn("Citation", max_chars=MAX_CITATION)})
        last = n == len(STEPS) - 1
        cols = st.columns(2 if last else 3)
        back = cols[0].form_submit_button("Back", disabled=n == 0, width="stretch")
        forward = not last and cols[1].form_submit_button("Next", type="primary", width="stretch")
        save = cols[-1].form_submit_button("Save profile", type="primary" if last else "secondary", width="stretch")
    if not (back or forward or save):
        return
    if n == 0:
        draft = replace(draft, investigator=investigator.strip(), institution=institution.strip(), career_stage=stage or "")
        st.session_state["profile_builtin"] = ranking == RANKINGS[1]
        # Leaving the built-in ranking starts the ranking as a new draft does, so none of the built-in terms or sentences stay behind.
        if source := BUILTIN_PROFILE if st.session_state["profile_builtin"] else BLANK if ranks_like_builtin(draft) else None:
            draft = replace(draft, keywords=dict(source.keywords), examples=source.examples, focus=source.focus, examples_name=source.examples_name, institutes=source.institutes)
    elif n == 1:
        examples = tuple(part.strip() for part in re.split(r"\n|(?<=[.?!])\s+", aims) if part.strip())
        if (forward or save) and not 3 <= len(examples) <= 6:
            st.error(f"Write three to six sentences. You wrote {len(examples)}.")
            return
        if (forward or save) and (long := next((e for e in examples if len(e) > MAX_SENTENCE), None)):
            st.error(f"A sentence holds at most {MAX_SENTENCE} characters. The one that begins \"{escape_markdown(long[:60])}\" holds {len(long):,}.")
            return
        if forward and ((summary.strip(), examples) != (draft.research_summary, draft.examples) or not draft.keywords):
            scorer = MLRelevanceScorer()
            draft = replace(draft, keywords={**suggest_terms((*examples, summary), scorer.document_frequency, scorer.documents), **draft.keywords})
        draft = replace(draft, research_summary=summary.strip(), examples=examples)
    elif n == 2:
        keywords, dropped, merged = read_terms(terms)
        draft = replace(draft, keywords=keywords, institutes=tuple(institutes))
        if notes := [f"{escape_markdown(t)} had no weight, so it was dropped." for t in dropped] + [f"{escape_markdown(a)} and {escape_markdown(b)} are one term, so the wizard kept it once with weight {w}." for a, b, w in merged]:
            st.session_state["profile_terms_warning"] = " ".join(notes)
    elif n == 4:
        cells = [["" if pd.isna(value) else str(value).strip() for value in row] for row in refs[["Key", "Citation", "PMID", "DOI"]].itertuples(index=False)]
        draft = replace(draft, expertise=expertise.strip(), resources=resources.strip(), prior_work=tuple(Reference(*row) for row in cells if any(row)))
    st.session_state["profile_draft"] = draft
    missing = " and ".join(text for text, have in ((f"example sentences under step 2 ({STEPS[1]})", draft.examples), (f"terms under step 3 ({STEPS[2]})", draft.keywords)) if not have)
    if save and missing:
        st.error(f"A profile needs {missing}. Nothing was saved.")
        return
    if save:
        _apply(db_path, lambda: draft, "Saved your profile. The Find view keeps the built-in ranking." if ranks_like_builtin(draft) else "Saved your profile. The Find view now ranks with it.")
    else:
        # The built-in ranking skips steps 2 to 4, which set the ranking, in both directions.
        skip = st.session_state.get("profile_builtin", False)
        st.session_state["profile_step"] = (0 if skip and n == 4 else n - 1) if back else (4 if skip and n == 0 else n + 1)
    st.rerun()

def profile_page(db_path: str) -> None:
    st.header("Profile")
    kind, text = st.session_state.pop("profile_notice", (None, ""))
    if kind:
        getattr(st, kind)(text)
    # The wizard reruns after it reads the terms table, so what it dropped or merged is shown on the next run.
    if terms_warning := st.session_state.pop("profile_terms_warning", None):
        st.warning(terms_warning)
    try:
        saved, unreadable = saved_profile(db_path), False
    except ProfileError as exc:
        saved, unreadable = None, True
        show_unreadable(exc)
    except sqlite3.Error as exc:
        saved, unreadable = None, False
        st.error(f"Could not open the database, so ranking uses the built-in profile. {escape_markdown(str(exc))}")
    if saved is None:
        st.info("Ranking uses the built-in profile (machine learning and data science).")
    else:
        st.caption(profile_sentence(saved))
    step = st.session_state.get("profile_step")
    if step is None:
        st.button("Set up my profile" if saved is None else "Edit my profile", type="primary", key="profile_setup", on_click=lambda: st.session_state.update(profile_step=0, profile_draft=saved or BLANK, profile_builtin=saved is not None and ranks_like_builtin(saved)))
    else:
        # The tour lights the step by this key.
        with st.container(key=f"profile_wizard_{step}"):
            _step(step, db_path, st.session_state["profile_draft"])

    st.divider()
    st.subheader("Export and import")
    st.download_button("Export profile", to_export(saved or BUILTIN_PROFILE), file_name="grant-matcher-profile.json", mime="application/json", disabled=unreadable, key="profile_export")
    st.caption("The button downloads the profile in use, which is the built-in one when none is saved. The file holds everything you entered, including your name, institution, research text and references. It holds no API key.")
    pasted = st.text_area("Import a profile", key="profile_import_text", persist_state="session", placeholder="Paste the contents of an exported profile file.", help="Open the exported file in a text editor, copy all of it and paste it here. Import profile replaces the saved profile, so export that one first if you want to keep it.")
    incoming = None
    if pasted.strip():
        try:
            incoming = from_export(pasted)
        except ProfileError as exc:
            st.error(escape_markdown(str(exc)))
        else:
            st.caption(f"This profile names {escape_markdown(incoming.investigator) or 'no investigator'} and holds {len(incoming.keywords)} terms.")
    st.button("Import profile", key="profile_import_save", disabled=incoming is None, on_click=_apply, args=(db_path, lambda: from_export(st.session_state.get("profile_import_text", "")), "Imported the profile. The Find view now ranks with it."))
    st.button("Reset to built-in", help="Deletes the saved profile, and ranking goes back to the built-in profile for machine learning and data science.", disabled=saved is None and not unreadable, on_click=_apply, args=(db_path, lambda: None, "Reset to the built-in profile."))
