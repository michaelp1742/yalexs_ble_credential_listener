#!/usr/bin/env sh
set -eu

# Build tests/hook/custom_components/yalexs_ble, the copy of core's yalexs_ble
# with the attribution hook that tests/test_hook.py loads as a custom
# integration.
# Usage: script/build-hook-copy.sh <core repository> [<commit>]
core=$1
commit=${2:-bb4d80ec79a1a4f805d7f9e33892ad7bcced6d3c}

root=$(git rev-parse --show-toplevel)
target="$root/tests/hook/custom_components/yalexs_ble"
rm -rf "$target"
mkdir -p "$target"
git -C "$core" archive "$commit" homeassistant/components/yalexs_ble |
    tar -x -C "$target" --strip-components=3

# Home Assistant loads a custom integration only when its manifest has a version.
"$root/script/run-in-env.sh" python - "$target/manifest.json" <<'PYTHON'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
manifest = json.loads(path.read_text())
manifest["version"] = "0.1.0"
path.write_text(json.dumps(manifest, indent=2) + "\n")
PYTHON
