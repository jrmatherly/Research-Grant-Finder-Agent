#!/usr/bin/env bash
# Builds macos/dist/Grant Matcher.app and Grant Matcher.dmg. Signs when CODESIGN_IDENTITY is set, notarizes when NOTARY_PROFILE is also set.
set -euo pipefail
cd "$(dirname "$0")/.."

app="macos/dist/Grant Matcher.app"
dmg="macos/dist/Grant Matcher.dmg"

uv run --locked --group macos pyinstaller --noconfirm --distpath macos/dist --workpath macos/build macos/grant_matcher.spec

echo "Smoke test: starting the server"
port=$(uv run --locked python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
smoke_home=$(mktemp -d)
stage=$(mktemp -d)
server=
trap '[[ -n $server ]] && kill "$server" 2>/dev/null; rm -rf "$smoke_home" "$stage"' EXIT
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

if [[ -n ${CODESIGN_IDENTITY:-} ]]; then
  codesign --verify --deep --strict --verbose=1 "$app"
fi

cp -R "$app" "$stage/"
ln -s /Applications "$stage/Applications"
rm -f "$dmg"
hdiutil create -volname "Grant Matcher" -srcfolder "$stage" -format UDZO "$dmg"

if [[ -n ${CODESIGN_IDENTITY:-} ]]; then
  codesign --sign "$CODESIGN_IDENTITY" --timestamp "$dmg"
  if [[ -n ${NOTARY_PROFILE:-} ]]; then
    xcrun notarytool submit "$dmg" --keychain-profile "$NOTARY_PROFILE" --wait
    xcrun stapler staple "$dmg"
  fi
fi

echo "App: $PWD/$app"
echo "Disk image: $PWD/$dmg"
