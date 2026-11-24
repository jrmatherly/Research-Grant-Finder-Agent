from __future__ import annotations
import sqlite3
import streamlit as st
from ..store import OpportunityStore
from .apply_page import database_error, model_settings, show_notices
from .markdown import escape_markdown

def settings_page(db_path: str, default_db: str) -> None:
    st.header("Settings")
    # Every view reads this key, so its value persists while another view is shown.
    st.text_input("Database", value=default_db, key="db_path", persist_state="session", help="The file that holds your results, your profile, your applications and your settings.")
    with st.container():
        show_notices()
    store = None
    try:
        # Opening the store creates the database and its folder, so a model can be set up before the first search.
        store = OpportunityStore(db_path)
        path = str(store.db_path)
        st.caption(f"These settings, except the API key, are saved in {f'`{path}`' if '`' not in path else escape_markdown(path)}, the file named under Database above.")
        model_settings(store, db_path, expanded=True)
    except (sqlite3.Error, OSError) as exc:
        st.error(database_error(db_path, exc))
    except ValueError as exc:
        st.error(escape_markdown(str(exc)))
    finally:
        if store is not None:
            store.close()
