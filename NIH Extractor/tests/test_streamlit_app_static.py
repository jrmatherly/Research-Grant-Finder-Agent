from pathlib import Path


def test_streamlit_app_avoids_session_state_items_attribute() -> None:
    app_text = Path("streamlit_app.py").read_text(encoding="utf-8")

    assert "st.session_state.items" not in app_text
    assert 'st.session_state["scored_items"]' in app_text


def test_streamlit_app_guards_against_callable_session_value() -> None:
    app_text = Path("streamlit_app.py").read_text(encoding="utf-8")

    assert "def get_scored_items_from_session" in app_text
    assert "callable(value)" in app_text
    assert 'del st.session_state["items"]' in app_text


def test_streamlit_score_bins_use_string_labels() -> None:
    app_text = Path("streamlit_app.py").read_text(encoding="utf-8")

    assert 'score_labels = ["0-25", "25-35", "35-70", "70-100"]' in app_text
    assert 'filtered["Score"].map(score_bin)' in app_text


def test_streamlit_app_reads_500_rows_by_default_and_warns_at_the_limit() -> None:
    app_text = Path("streamlit_app.py").read_text(encoding="utf-8")

    assert 'limit = st.slider("Rows per source", min_value=25, max_value=1000, value=500, step=25, key="find_rows", persist_state="session")' in app_text
    assert "if summary.capped:" in app_text


def test_streamlit_results_table_labels_the_date_as_an_expiration() -> None:
    app_text = Path("streamlit_app.py").read_text(encoding="utf-8")

    assert '"Close Date": st.column_config.DateColumn("Expires"' in app_text


# It reads the source, so it holds how the page is written and not what the browser shows.
def test_every_keyed_apply_widget_persists_except_the_api_key_and_the_consent_box() -> None:
    import ast
    page = Path(__file__).resolve().parents[1] / "nih_grant_matcher" / "ui" / "apply_page.py"
    drawn = {}
    for node in ast.walk(ast.parse(page.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("selectbox", "text_input", "text_area", "checkbox", "toggle"):
            given = {k.arg: k.value for k in node.keywords}
            secret = isinstance(given.get("type"), ast.Constant) and given["type"].value == "password"
            persists = isinstance(given.get("persist_state"), ast.Constant) and given["persist_state"].value == "session"
            drawn[ast.unparse(given["key"])] = (secret, persists)
    assert [key for key, (secret, _) in drawn.items() if secret] == ["'apply_llm_key'"]
    # The API key is cleared after Save, and the consent box is set from the record on every run.
    assert sorted(key for key, (_, persists) in drawn.items() if not persists) == ["'apply_llm_key'", "consent_key"]
