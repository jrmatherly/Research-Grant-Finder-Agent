---
paths:
  - "**/streamlit_app.py"
  - "**/tests/test_streamlit_app_static.py"
---

# Dashboard rules

- Store results under `st.session_state["scored_items"]`. Never read or write a session key named `items` with attribute access, because that name resolves to a method of the session object.
- `tests/test_streamlit_app_static.py` asserts literal strings in `streamlit_app.py`, including text inside comments. Run that test file after every edit to the dashboard.
- Keep the score bin labels as the strings `"0-25"`, `"25-35"`, `"35-70"`, and `"70-100"`.
