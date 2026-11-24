from __future__ import annotations
import sqlite3
import streamlit as st
from ..store import OpportunityStore
from .apply_page import model_settings, show_notices
from .markdown import escape_markdown

def settings_page(db_path: str) -> None:
    st.header("Settings")
    with st.container():
        show_notices()
    store = None
    try:
        # Opening the store creates the database and its folder, so a model can be set up before the first search.
        store = OpportunityStore(db_path)
        model_settings(store, db_path, expanded=True)
    except (sqlite3.Error, ValueError, OSError) as exc:
        st.error(escape_markdown(str(exc)))
    finally:
        if store is not None:
            store.close()
