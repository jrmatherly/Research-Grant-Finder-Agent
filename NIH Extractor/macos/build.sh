#!/usr/bin/env bash
# Builds macos/dist/Grant Matcher.app and Grant Matcher.dmg. Signs when CODESIGN_IDENTITY is set. Notarizes when NOTARY_PROFILE (a keychain profile) or APPLE_API_KEY_P8 with APPLE_API_KEY_ID and APPLE_API_ISSUER_ID (an App Store Connect key) is also set.
set -euo pipefail
cd "$(dirname "$0")/.."

app="macos/dist/Grant Matcher.app"
dmg="macos/dist/Grant Matcher.dmg"

# Streamlit's wheel has no licence files, and the app must carry them. The checksums fail the build when a new Streamlit changes either file.
streamlit_version=$(uv run --locked python -c 'from importlib.metadata import version; print(version("streamlit"))')
licences=macos/build/licenses/streamlit
mkdir -p "$licences"
for file in LICENSE NOTICES; do
  curl -fsSL -o "$licences/$file" "https://raw.githubusercontent.com/streamlit/streamlit/$streamlit_version/$file"
done
(cd "$licences" && shasum -a 256 -c "$OLDPWD/macos/streamlit-licenses.sha256") || {
  echo "Streamlit $streamlit_version ships different licence files. Read them in $licences, then update macos/streamlit-licenses.sha256." >&2
  exit 1
}

uv run --locked --group macos pyinstaller --noconfirm --distpath macos/dist --workpath macos/build macos/grant_matcher.spec

echo "Smoke test: starting the server"
port=$(uv run --locked python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
smoke_home=$(mktemp -d)
stage=$(mktemp -d)
server=
# || true: under set -e, bash 3.2 (the runner's) exits 1 from the trap when the server is already gone.
trap '[[ -n $server ]] && kill "$server" 2>/dev/null || true; rm -rf "$smoke_home" "$stage"' EXIT
# A temporary HOME keeps the test out of the real data folder.
HOME="$smoke_home" STREAMLIT_SERVER_SCRIPT_HEALTH_CHECK_ENABLED=true "$app/Contents/MacOS/Grant Matcher" --serve "$port" >"$smoke_home/server.log" 2>&1 &
server=$!
healthy=
for _ in $(seq 60); do
  if curl -fsS "http://127.0.0.1:$port/_stcore/script-health-check" >/dev/null 2>&1; then healthy=1; break; fi
  kill -0 "$server" 2>/dev/null || break
  sleep 0.5
done
kill "$server" 2>/dev/null || true
wait "$server" 2>/dev/null || true
if [[ -z $healthy ]]; then
  echo "Smoke test failed: the dashboard script did not run cleanly within 30 s. Server output:" >&2
  cat "$smoke_home/server.log" >&2
  exit 1
fi
echo "Smoke test passed"
# A release must not go out without the licence texts of what it bundles.
test -s "$app/Contents/Resources/licenses/streamlit/NOTICES"

if [[ -n ${CODESIGN_IDENTITY:-} ]]; then
  codesign --verify --deep --strict --verbose=1 "$app"
fi

cp -R "$app" "$stage/"
ln -s /Applications "$stage/Applications"
rm -f "$dmg"
hdiutil create -volname "Grant Matcher" -srcfolder "$stage" -format UDZO "$dmg"

if [[ -n ${CODESIGN_IDENTITY:-} ]]; then
  codesign --sign "$CODESIGN_IDENTITY" --timestamp "$dmg"
  notarize=
  if [[ -n ${NOTARY_PROFILE:-} ]]; then
    notarize=1
    credentials=(--keychain-profile "$NOTARY_PROFILE")
  elif [[ -n ${APPLE_API_KEY_P8:-} ]]; then
    notarize=1
    key="$smoke_home/AuthKey.p8"
    (umask 077 && printf '%s\n' "$APPLE_API_KEY_P8" >"$key")
    credentials=(--key "$key" --key-id "${APPLE_API_KEY_ID:?}" --issuer "${APPLE_API_ISSUER_ID:?}")
  fi
  if [[ -n $notarize ]]; then
    out=$(xcrun notarytool submit "$dmg" "${credentials[@]}" --wait --timeout 30m --output-format json)
    echo "$out"
    # notarytool exits 0 for a finished but rejected submission, so the status decides.
    status=$(plutil -extract status raw -o - - <<<"$out")
    if [[ $status != Accepted ]]; then
      echo "Notarization ended as '$status'. Details: xcrun notarytool log $(plutil -extract id raw -o - - <<<"$out" || true)" >&2
      exit 1
    fi
    xcrun stapler staple "$dmg"
  fi
fi

echo "App: $PWD/$app"
echo "Disk image: $PWD/$dmg"
