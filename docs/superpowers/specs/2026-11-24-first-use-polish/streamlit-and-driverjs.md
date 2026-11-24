# Research for the next dashboard release (2026-11-24)

Goal: pick small refinements for the next release of the Streamlit dashboard (Streamlit 1.67.0 locked, floor 1.59; driver.js 1.14.0 vendored; macOS app in a pywebview WKWebView), each backed by a primary source.

Labels: **[primary]** read in a primary source; **[installed]** read in installed code; **[inferred]** reasoning, not observed.

Paths used below:
- `ST` = `/Users/jason/dev/Research-Grant-Finder-Agent/NIH Extractor/.venv/lib/python3.13/site-packages/streamlit` (Streamlit 1.67.0)
- `DRV` = `/Users/jason/dev/Research-Grant-Finder-Agent/NIH Extractor/nih_grant_matcher/ui/vendor/driver.js.iife.js` (47,077 bytes, one line; offsets are character offsets)
- `CSS` = `/Users/jason/dev/Research-Grant-Finder-Agent/NIH Extractor/nih_grant_matcher/ui/vendor/driver.css`
- Streamlit frontend files were fetched at tag `1.67.0` with `gh api repos/streamlit/streamlit/contents/...?ref=1.67.0` into `/private/tmp/claude-501/-Users-jason--claude-spares-spare-A37e9T/fe24b3be-f76c-4452-9c22-24113b8b5114/scratchpad/st-src/`.

## 1. Streamlit `st.dataframe` selections

### 1a. Repeat click on the selected cell; clearing from Python

**A repeat click that leaves the selection unchanged sends nothing, so `on_select` does not run.** Two guards prevent it.
- `useSelectionHandler.ts` (tag 1.67.0, lines 160-233): `processSelectionChange` compares the new `GridSelection` with the current one (`cellSelectionChanged = !isEqual(newSelection.current, gridSelection.current)`) and only calls `syncSelectionState` when something changed. **[primary, source at tag 1.67.0]**
- `useWidgetState.ts` (tag 1.67.0, lines 474-497): `createSyncSelectionState` serialises the selection and calls `widgetMgr.setStringValue` only `if (!isUnchanged)`; the comment says "Only update if there is actually a difference to the previous selection state". **[primary]**
- Whether Glide Data Grid itself turns a second click on the selected cell into a deselect (which would send an empty selection and fire `on_select`) I did not verify. **[not verified]** Check: run a single-cell dataframe with an `on_select` callback that logs, click one cell twice.
- No documented way makes a repeat click fire. Open issue #10212 "Dataframe row click events" (created 2025-01-19) asks for click events separate from selection. **[primary, title only]**

**Clearing from Python is documented and works through Session State.**
- `ST/elements/arrow.py` lines 135-148 and 203-232 (1.67.0): "Selection states can be programmatically set through Session State"; Example 2 writes `st.session_state.data = {"selection": {"cells": [[0, "a"]]}}`. Programmatic selection works for every mode except `"multi-cell"`. **[installed]**
- `arrow.py` lines 465-570: `_validate_selection_state` accepts an empty selection and drops out-of-range rows and cells (`0 <= cell[0] < num_rows`, column in `column_names`). Lines 1411-1435: on `widget_state.value_changed` the validated state goes to the frontend once, as `proto.selection_state`. **[installed]**
- Release notes 1.56.0 add programmatic selection ("supports programmatically setting selections via the `selection` parameter"), so the floor 1.59 has it. https://docs.streamlit.io/develop/quick-reference/release-notes/2026 **[primary]**
- **Floor caveat.** Issue #17195 "Programmatically set selections fail for empty selection" (opened 2026-09-29 on 1.63.0, closed 2026-10-01): clearing a second time updated Python but left the grid showing the old selection. The 1.65.0 notes (2026-10-02) list the fix: "Clearing a dataframe selection through Session State a second time also unchecks the rows in the grid". https://github.com/streamlit/streamlit/issues/17195 **[primary]** So between 1.59 and 1.64 a repeated programmatic clear can leave a stale highlight. Raising the floor to 1.65 removes that. **[inferred from the two sources]**
- **Changing the key** gives a fresh widget, so the selection starts empty. A maintainer-side comment on issue #17026 recommends exactly this (`key=f"queue:{st.session_state['gen']}"`), plus `selection_default` to carry a chosen row across. https://github.com/streamlit/streamlit/issues/17026 **[primary]**
- Writing `st.session_state[key]` inside that dataframe's own `on_select` callback: callbacks run before the script, so the "cannot be modified after the widget is instantiated" error should not apply. **[inferred, not run]**

### 1b. Data changes under the same key

**The selection is kept at the same row position and column name. It is not cleared.**
- `ST/elements/arrow.py` lines 1373-1395 (1.67.0): `compute_and_register_element_id(..., key_as_main_identity={"selection_mode", "is_selection_activated"}, data=...)`. With a key, only the selection settings form the identity, so new data keeps the same element ID and widget state. The comment above it: "There are some edge cases where selections can become orphaned when the data changes - e.g. when rows get removed. The frontend can handle this without errors, but it might be a nice enhancement to automatically reset the backend & frontend selection state in this case." **[installed]**
- `DataframeSelectionSerde.deserialize` (lines 317-374) does not filter user selections against the new row count. Only programmatic values pass `_validate_selection_state`. So after a filter to fewer rows, `event.selection.cells` can name a row position that no longer exists, or a different record at the same position. **[installed]** The 1.67.0 frontend's behaviour when the stored cell is out of range was not checked. **[not verified]**
- Issue #17026, open, created 2026-09-18: "Keyed `st.dataframe` / `st.data_editor` keep positional selection and edit state across a data change, so actions land on the wrong row". It quotes the same `key_as_main_identity` line and the orphan comment. https://github.com/streamlit/streamlit/issues/17026 **[primary]**
- Issue #10701 "Preserve Selection, Sorting and Scrolling Position in st.dataframe" is open. **[primary, title only]**
- **Version history.** Cell selections first shipped in 1.49.0 (2025-08-26): "Dataframes support cell selections!" https://docs.streamlit.io/develop/quick-reference/release-notes/2025 **[primary]**. In 1.59.0, `lib/streamlit/elements/arrow.py` already has the orphan comment (line 1047), the same `key_as_main_identity` (line 1051), `single-cell` and the programmatic `value_changed` path (line 1081). Fetched with `gh api ...contents/lib/streamlit/elements/arrow.py?ref=1.59.0`. **[primary]**
- Selection changes between 1.59 and 1.67 in the release notes: 1.60.0 "`st.dataframe` now preserves row selections when the user sorts the table"; 1.65.0 the repeated-clear fix above. There is no change to data-change behaviour. **[primary]**

### 1c. Newest Streamlit and changes since 1.67.0

- **1.67.0 is the newest release.** PyPI `info.version` = 1.67.0, uploaded 2026-11-05. The GitHub `releases/latest` tag is 1.67.0, published 2026-11-05. **[primary]**
- Nothing newer exists, so there is no changelog after 1.67.0. The 1.67.0 notes themselves say "Custom Components v2 events, `st.menu_button` selections, and `ButtonColumn` clicks are no longer lost" and "Type hints for `st.components` match their runtime behavior". There is no dataframe-selection line. https://docs.streamlit.io/develop/quick-reference/release-notes **[primary]**

## 2. driver.js

### 2a. Version and advisories

- **1.14.0 is the newest release.** npm `dist-tags.latest` = 1.14.0, published 2026-11-13T14:01:57Z. GitHub release 1.14.0 on `nilbuild/driver.js` (the npm `repository` field), 2026-11-13. **[primary]**
- **There are no advisories at any version.** GitHub Advisory Database (`gh api "advisories?ecosystem=npm&affects=driver.js"`) returned 0. Repository security advisories returned 0. The npm bulk advisory endpoint returned `{}` for 1.14.0, 1.3.0 and 0.9.8. OSV `query` for npm/driver.js returned `{}`. Snyk https://security.snyk.io/package/npm/driver.js says "No direct vulnerabilities have been found for this package in Snyk's vulnerability database". **[primary, checked 2026-11-24]**
- **An unreleased fix is relevant.** PR #631 "fix: skip hidden controls when trapping focus" merged 2026-11-14T15:25Z, after 1.14.0. Before it, Tab stuck on a `visibility: hidden` control inside the highlighted element. The vendored file has no `visibility` check: `fe(e)` is `getComputedStyle(e).pointerEvents!=='none'&&we(e)`, and `we` only checks offsetWidth/offsetHeight/getClientRects (DRV offsets ~4727, ~10200). https://github.com/nilbuild/driver.js/pull/631 **[primary + installed]**

### 2b. `disableActiveInteraction: true` in 1.14.0

What it does (all **[installed]**):
- It adds a CSS class. `Fn` (DRV ~37020): `let r=E(e,n,'disableActiveInteraction')===!0;r&&t.classList.add('driver-no-interaction')`. A MutationObserver re-adds it (`jn(t,()=>['driver-active-element',...r?['driver-no-interaction']:[]...])`).
- That class sets pointer-events. `CSS` line 1: `.driver-no-interaction,.driver-no-interaction *{pointer-events:none!important}`.
- It blocks mouse events in the capture phase. `Kn` (DRV ~38300) returns `'disabled'` when `e.ui.blocksInteraction&&E(e,n,'disableActiveInteraction')`, but only for `MouseEvent` types: `Wn` maps `pointerdown/mousedown/pointerup/mouseup` and `click/auxclick/contextmenu/dblclick`. `nr` registers those on `window` with `capture:!0`, and `er`/`Qn` call `preventDefault` and `stopImmediatePropagation`.
- It does **not** use `inert`: the token `inert` occurs 0 times in DRV. No keyboard event is blocked for the highlighted element.
- It changes focus placement. `Yt` (DRV ~25035) only returns the element to focus when `disableActiveInteraction!==!0`, so the tour does not focus the highlighted element. The popover gets focus instead: `tt` focuses the Next button, else the wrapper with `tabindex=-1` (DRV ~13289).

Keyboard reach:
- **Tab cannot reach controls inside the highlighted element.** The focus trap `ur` (DRV 41458): `if(!e.state.isInitialized||!(t.key==='Tab'||t.keyCode===9)||D(e))return; ... i=[...new Set(pe([...r?[r]:[],...n?[n]:[],...Array.from(document.querySelectorAll('.driver-allowed-element'))]))] ... t.preventDefault(), t.shiftKey?(...)-1]||o)?.focus():(...)+1]||a)?.focus()`. It collects the popover, the active element and `.driver-allowed-element` nodes, but `pe` filters with `fe`, which drops anything whose computed `pointer-events` is `none`. Under `driver-no-interaction` that is every descendant. So Tab cycles the popover (and allowed elements) only. `D(e)` is `allowPageInteraction`: when that is true there is no trap at all. **[installed]**
- **If focus is already inside the element, keys still work.** That can happen through a screen reader's virtual cursor or focus set before the tour or by script. No key handler is suppressed, so Space, Enter and arrow keys on a radio group would act natively. **[inferred from the absence of keyboard blocking; not run]**
- In that case driver.js also stops reading arrow and Escape keys. `pr` (DRV ~42019) runs on `keyup`: `!(!n||r||i||ar(e))&&(t.key==='Escape'?e.tour.escape():t.key==='ArrowRight'?e.tour.arrowRight():t.key==='ArrowLeft'&&e.tour.arrowLeft())`, where `n=e.config.allowKeyboardControl??!0`. `ar(e)` is true when the focused element is a "widget" (`je`: input, textarea, select, `[role=radiogroup]`, `[role=grid]`, `[role=listbox]`, ...) inside the element or an allowed region. **[installed]**

Key bindings and listeners (DRV ~42891-43215, **[installed]**):
- `window.addEventListener('keydown',r,!0)` is capture (`dr`, which tracks widget keys).
- `window.addEventListener('keyup',t,!1)` is bubble (`pr`: Escape, ArrowRight, ArrowLeft).
- `window.addEventListener('keydown',n,!1)` is bubble (`fr` plus `ur`, the Tab trap).
- `cr` also adds capture listeners for `keydown`, `keypress` and `keyup` on `window`. They call `preventDefault` only for auto-repeat or carried-over keys whose path includes the popover wrapper (`sr`).
- Escape, ArrowRight and ArrowLeft act on **keyup**. Tab acts on **keydown**. Escape calls `e.tour.escape()`.

### 2c. Safari / WebKit issues (repo `nilbuild/driver.js`)

Searches for safari (7 hits), webkit (4), ios (2), wkwebview (0), focus-visible (3), "svg overlay" (6) and "click through" (9) turned up two relevant items:
- #626 "TypeError: target.closest is not a function when popover click target is a non-Element Node", closed 2026-10-15. In WebKit (desktop and iOS Safari), a click on bare popover text has a Text node as its target. The capture-phase handler threw, and the page "appears stuck until reload". It names 1.3.6 onward up to 1.8.0 as affected, and it is closed. https://github.com/nilbuild/driver.js/issues/626 **[primary]** Whether 1.14.0 contains the fix: the 1.14.0 click path uses `composedPath()`/`Bn` rather than `target.closest`. **[installed, partial; I did not find the fixing commit]**
- #631 above: its E2E focus suite passed in WebKit.
- #558 "Popover arrow is not pointing to element" (closed 2026-06-25) is a placement report with no browser named. **[primary]**
- No issue for the overlay SVG, `:focus-visible` or clicks through the overlay in Safari or WKWebView. **[primary, search results]**

## 3. pywebview on macOS (6.2.1 locked; PyPI latest is also 6.2.1)

- **Escape reaches the page.** The installed `webview/platforms/cocoa.py` (6.2.1) lines 512-544: `WebKitHost.keyDown_` only intercepts keys with `NSCommandKeyMask` (Cmd+X/C/V/A/Z/Q/W). Every other key goes to `super().keyDown_(event)`, the WKWebView. There is no `keyUp_` override. So Escape and the arrow keys arrive as DOM `keydown`/`keyup`. **[installed]** Not run in the built app. **[not verified]**
- The old interception is gone. In #996 (closed 2023-01-17), Cmd combinations never reached JS because of `performKeyEquivalent_`. The thread says it was switched to `keyDown_`. https://github.com/r0x0r/pywebview/issues/996 **[primary]**
- **An alert sound is possible.** #1722 "mac alert sound upon keyboard presses" (closed 2026-02-04 as stale, no fix): the Cocoa window plays the system alert on key presses the web content does not handle, even with JS listeners. The maintainer said a fix was tried and reverted. https://github.com/r0x0r/pywebview/issues/1722 **[primary]** driver.js handles Escape on keyup without `preventDefault` on keydown, so pressing Escape may beep in the app. **[inferred, not run]**
- Fixed overlays: no pywebview issue found about `position: fixed`, an SVG overlay or a popover appended to `document.body`. One query timed out (network). The window is a WKWebView, so the WebKit notes in 2c apply. **[inferred]**
- Fullscreen: whether Escape exits native fullscreen before the page sees it was not verified. pywebview's own `toggle_fullscreen` is menu-driven, Cmd+Ctrl+F at cocoa.py ~1141. **[not verified]**

## 4. `~` in a user-typed path

- Python docs 3.15.2, `os.path.expanduser`: "If the expansion fails or if the path does not begin with a tilde, the path is returned unchanged." https://docs.python.org/3/library/os.path.html **[primary]**
- `pathlib.Path.expanduser`: "Return a new path with expanded `~` and `~user` constructs, as returned by `os.path.expanduser()`. If a home directory can't be resolved, `RuntimeError` is raised." https://docs.python.org/3/library/pathlib.html **[primary]**
- Tools that expand `~`:
  - pandas 3.1.1 `pandas/io/common.py` lines 183-198: `_expand_user` calls `os.path.expanduser` on every string path, through `stringify_path` (line 280), so `pd.read_csv("~/x.csv")` works. **[installed]**
  - git: config values of the `path` type are canonicalised "by expanding a leading `~` to the value of `$HOME` and `~user` to the home directory for the specified user". https://git-scm.com/docs/git-config (version selector 2.56.1) **[primary]**
- Downsides, run on Python 3.13.15 (`uv run --no-project python -I`) **[run]**:
  - `/abs/x.db`, `rel/x.db` and `a/~/b` come back unchanged.
  - `~/x.db` becomes `/Users/<user>/x.db`.
  - `~nosuchuser123/x.db` raises `RuntimeError: Could not determine home directory.` from `Path.expanduser`, while `os.path.expanduser` returns it unchanged. Catch `RuntimeError`, or use `Path(os.path.expanduser(text))`.
  - A leading space (`' ~/x.db'`) is not expanded, so strip the text first.
  - `Path('')` becomes `.` (Path's own behaviour, not expanduser), so check for empty input before building the Path.
  - A real directory literally named `~` (`./~/x`) would be redirected to home. This is rare. **[inferred]**

## Not verified

- Whether Glide turns a second click on the selected cell into a deselect (which would fire `on_select`). Run a single-cell dataframe and click a cell twice.
- How the 1.67.0 grid draws a stored cell whose row no longer exists after a filter.
- Writing `st.session_state[key]` from inside that dataframe's own `on_select` callback (no error expected, not run).
- Escape and keyup delivery, the alert beep, and fullscreen Escape in the built `Grant Matcher.app`.
- Which commit fixed driver.js #626, and confirmation that 1.14.0 contains it.
