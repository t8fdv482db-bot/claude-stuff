#!/usr/bin/env bash
# Lint, unit-test, build and verify the place. Run from the haunted-brainrot folder.
# Requires: selene, lune, rojo (cargo install selene lune rojo, or via aftman/rokit).
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== selene lint"
selene src
echo "== unit tests (lune)"
lune run tests/run
echo "== rojo build"
mkdir -p build
rojo build default.project.json -o build/HauntedBrainrot.rbxlx
echo "== verify build"
lune run tests/verify_build
