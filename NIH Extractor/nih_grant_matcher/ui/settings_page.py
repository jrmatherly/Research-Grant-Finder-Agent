from __future__ import annotations
import sqlite3
import streamlit as st
from ..store import OpportunityStore
from .apply_page import database_error, model_settings, show_notices
from .markdown import escape_markdown

def settings_page(db_path: str) -> None:
    st.header("Settings")
    with st.container():
        show_notices()
    store = None
    try:
        # Opening the store creates the database and its folder, so a model can be set up before the first search.
        store = OpportunityStore(db_path)
        path = str(store.db_path)
        st.caption(f"These settings are saved in {f'`{path}`' if '`' not in path else escape_markdown(path)}, the file named under Database in the sidebar.")
        model_settings(store, db_path, expanded=True)
    except (sqlite3.Error, OSError) as exc:
        st.error(database_error(db_path, exc))
    except ValueError as exc:
        st.error(escape_markdown(str(exc)))
    finally:
        if store is not None:
            store.close()
