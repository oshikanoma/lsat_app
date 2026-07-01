#!/bin/bash
# Sync the compiled LSAT SvelteKit bundle into the Android app's assets and
# inject the native bridgeCommand shim into the SPA shell. Run after any change
# to the ts/routes/lsat-* pages (rebuild first with: ./ninja sveltekit).
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)/out/sveltekit"
DEST="/Users/alphaintern/lsat-mobile/Anki-Android/AnkiDroid/src/main/assets/lsat-web"

if [ ! -d "$SRC" ]; then
  echo "error: $SRC not found. Run ./ninja sveltekit first." >&2
  exit 1
fi

rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$SRC"/. "$DEST"/

python3 - "$DEST/index.html" <<'PY'
import sys

path = sys.argv[1]
html = open(path, encoding="utf-8").read()

bridge = '''\t\t<!-- homebase: native bridge, mirrors the desktop Qt bridgeCommand(arg, cb) -->
\t\t<script>
\t\t\t(function () {
\t\t\t\twindow.__lsatCbs = {};
\t\t\t\twindow.__lsatSeq = 0;
\t\t\t\tfunction send(arg, cb) {
\t\t\t\t\tif (!window.lsatNative) { if (cb) cb(null); return false; }
\t\t\t\t\tvar id = -1;
\t\t\t\t\tif (cb) { id = ++window.__lsatSeq; window.__lsatCbs[id] = cb; }
\t\t\t\t\ttry { window.lsatNative.cmd(String(arg), id); } catch (e) { if (cb) cb(null); }
\t\t\t\t\treturn false;
\t\t\t\t}
\t\t\t\twindow.bridgeCommand = window.pycmd = send;
\t\t\t\twindow.__lsatResolve = function (id, jsonText) {
\t\t\t\t\tvar cb = window.__lsatCbs[id];
\t\t\t\t\tif (!cb) return;
\t\t\t\t\tdelete window.__lsatCbs[id];
\t\t\t\t\tvar val = null;
\t\t\t\t\ttry { val = jsonText == null ? null : JSON.parse(jsonText); } catch (e) { val = null; }
\t\t\t\t\tcb(val);
\t\t\t\t};
\t\t\t})();
\t\t</script>
'''

if "__lsatResolve" not in html:
    marker = '<meta name="viewport" content="width=device-width, initial-scale=1" />'
    html = html.replace(marker, marker + "\n" + bridge, 1)
    open(path, "w", encoding="utf-8").write(html)
    print("injected native bridge into index.html")
else:
    print("bridge already present")
PY

echo "synced LSAT web bundle -> $DEST"
