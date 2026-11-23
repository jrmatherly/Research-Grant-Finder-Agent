#!/usr/bin/env bash
# Rehearses a real Sparkle update of the app from 0.0.1 to 0.0.2 on this Mac, with a bundle ID and a throwaway key of its own.
#
#   macos/rehearse-update.sh [--bad-signature | --stop-feed | --from-dmg]
#
#   (none)           a good feed. Exits 0 once the app reads 0.0.2, has relaunched with its server, and nothing of Sparkle's is left.
#   --bad-signature  the feed's signature is from another key. Sparkle says the update is improperly signed.
#   --stop-feed      nothing serves the feed. The app opens with no alert, and a check reports the error.
#   --from-dmg       the app runs from the mounted disk image. Sparkle says to move it.
#
# The three failure modes exit 0 when the app still reads 0.0.1 after REHEARSE_SECONDS (180 by default). That proves the disk only. The message is in Sparkle's window.
set -euo pipefail
cd "$(dirname "$0")/.."

mode=happy
case ${1:-} in
  '') ;;
  --bad-signature) mode=bad-signature ;;
  --stop-feed) mode=stop-feed ;;
  --from-dmg) mode=from-dmg ;;
  *) echo "usage: macos/rehearse-update.sh [--bad-signature | --stop-feed | --from-dmg]" >&2; exit 2 ;;
esac
deadline=${REHEARSE_SECONDS:-180}
case $deadline in ''|*[!0-9]*|0*) echo "rehearse: REHEARSE_SECONDS must be a positive number of seconds" >&2; exit 2 ;; esac
# An update between two ad hoc builds is unproven, and Sparkle checks the team of a signed app.
[ -n "${CODESIGN_IDENTITY:-}" ] || { echo "rehearse: set CODESIGN_IDENTITY to a Developer ID Application identity" >&2; exit 2; }
# With one of these set, build.sh would send both throwaway builds to Apple.
unset NOTARY_PROFILE APPLE_API_KEY_ID APPLE_API_ISSUER_ID APPLE_API_KEY_P8

bundle_id=net.matherly.gm-rehearsal
agents_dir=$HOME/Library/LaunchAgents
work=$(mktemp -d)
server=
mount=
app_path=

cleanup() {
  [ -z "$app_path" ] || pkill -f "$app_path/Contents/MacOS/Grant Matcher" || true
  [ -z "$server" ] || kill "$server" 2>/dev/null || true
  [ -z "$mount" ] || hdiutil detach -quiet -force "$mount" || true
  defaults delete "$bundle_id" 2>/dev/null || true
  rm -rf "$work" "macos/dist/Grant Matcher.app" "macos/dist/Grant Matcher.dmg" "$HOME/Library/Caches/$bundle_id" "$HOME/Library/HTTPStorages/$bundle_id" "$HOME/Library/Preferences/$bundle_id.plist" || true
}
trap cleanup EXIT

echo "rehearse: the rehearsal app is also named Grant Matcher, so it reads the real database in ~/Library/Application Support/Grant Matcher, and its launches rotate the real app's server.log out of ~/Library/Logs/Grant Matcher." >&2

# CryptoKit, so the Keychain and the real key are not used. Prints the seed, then its public key.
keypair() {
  swift -e 'import CryptoKit
let k = Curve25519.Signing.PrivateKey()
print(k.rawRepresentation.base64EncodedString())
print(k.publicKey.rawRepresentation.base64EncodedString())'
}
keys=$(keypair)
seed=$(sed -n 1p <<<"$keys")
export GRANT_MATCHER_BUNDLE_ID=$bundle_id SPARKLE_PUBLIC_KEY
SPARKLE_PUBLIC_KEY=$(sed -n 2p <<<"$keys")

# Copies, because build.sh writes both builds to the same paths in macos/dist.
mkdir -p "$work/install" "$work/feed"
GRANT_MATCHER_VERSION=0.0.1 /bin/bash macos/build.sh
cp -R "macos/dist/Grant Matcher.app" "$work/install/"
cp "macos/dist/Grant Matcher.dmg" "$work/old.dmg"
GRANT_MATCHER_VERSION=0.0.2 /bin/bash macos/build.sh
# A name with no space, so the enclosure URL needs no encoding.
new_dmg=$work/feed/Grant-Matcher-0.0.2-arm64.dmg
cp "macos/dist/Grant Matcher.dmg" "$new_dmg"

port=$(/usr/bin/python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
feed_key=$seed
if [ "$mode" = bad-signature ]; then feed_key=$(keypair | sed -n 1p); fi
SPARKLE_ED_KEY=$feed_key APPCAST_DOWNLOAD_BASE=http://127.0.0.1:$port /bin/bash macos/make-appcast.sh "$new_dmg" 0.0.2 >"$work/feed/appcast.xml"
app_path="$work/install/Grant Matcher.app"
if [ "$mode" != bad-signature ]; then /bin/bash macos/verify-appcast.sh "$app_path" "$new_dmg" "$work/feed/appcast.xml"; fi

if [ "$mode" != stop-feed ]; then
  /usr/bin/python3 -m http.server "$port" --bind 127.0.0.1 --directory "$work/feed" >/dev/null 2>&1 &
  server=$!
  for _ in $(seq 20); do
    if curl -fsS -o /dev/null "http://127.0.0.1:$port/appcast.xml" 2>/dev/null; then break; fi
    sleep 0.5
  done
  curl -fsS -o /dev/null "http://127.0.0.1:$port/appcast.xml" || { echo "rehearse: the feed server did not answer within 10 s" >&2; exit 1; }
fi

if [ "$mode" = from-dmg ]; then
  mount=$work/mount
  mkdir "$mount"
  hdiutil attach -quiet -nobrowse -readonly -mountpoint "$mount" "$work/old.dmg"
  app_path="$mount/Grant Matcher.app"
fi

agents_before=$(ls "$agents_dir" 2>/dev/null || true)
# Sparkle reads this default in place of SUFeedURL in Info.plist.
defaults write "$bundle_id" SUFeedURL "http://127.0.0.1:$port/appcast.xml"
open "$app_path"
echo "rehearse: running $app_path ($mode). In the Grant Matcher menu choose Check for Updates…, then Install Update, then Install and Relaunch. Waiting up to $deadline s." >&2

disk_version() { plutil -extract CFBundleShortVersionString raw -o - "$app_path/Contents/Info.plist"; }
sparkle_jobs() {
  local all
  # Apart, because || true for grep finding nothing would also hide launchctl failing.
  all=$(launchctl print "gui/$(id -u)")
  grep -oE "gm-rehearsal-sparkle-[a-z]+" <<<"$all" | sort -u || true
}

updated=
for _ in $(seq "$deadline"); do
  if [ "$(disk_version)" = 0.0.2 ]; then updated=1; break; fi
  sleep 1
done

if [ -z "$updated" ]; then
  [ "$mode" != happy ] || { echo "rehearse: the app still reads 0.0.1 after $deadline s" >&2; exit 1; }
  [ "$(disk_version)" = 0.0.1 ] || { echo "rehearse: $mode: the app reads '$(disk_version)', not 0.0.1" >&2; exit 1; }
  echo "rehearse: $mode: the app still reads 0.0.1, as expected" >&2
  exit 0
fi
[ "$mode" = happy ] || { echo "rehearse: $mode: the app reads 0.0.2, and it must not" >&2; exit 1; }

# The new bundle on disk does not prove the relaunch. The window and the server are two processes of this copy.
running=0
for _ in $(seq 30); do
  # || true: pgrep finds nothing between the old app's exit and the relaunch, and pipefail would end the script there.
  running=$(($({ pgrep -f "$app_path/Contents/MacOS/Grant Matcher" || true; } | wc -l)))
  if [ "$running" -ge 2 ]; then break; fi
  sleep 1
done
[ "$running" -ge 2 ] || { echo "rehearse: the app reads 0.0.2, but $running of its 2 processes run after 30 s" >&2; exit 1; }
codesign --verify --deep --strict "$app_path" || { echo "rehearse: the updated app does not pass codesign --verify" >&2; exit 1; }
left=
for _ in $(seq 30); do
  left=$(sparkle_jobs)
  if [ -z "$left" ]; then break; fi
  sleep 1
done
[ -z "$left" ] || { echo "rehearse: launchd jobs remain after the install: $left" >&2; exit 1; }
[ "$(ls "$agents_dir" 2>/dev/null || true)" = "$agents_before" ] || { echo "rehearse: $agents_dir changed during the install" >&2; exit 1; }
echo "rehearse: updated to 0.0.2 and relaunched with its server. No launchd job or LaunchAgents file is left." >&2
