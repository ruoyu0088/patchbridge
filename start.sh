#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
export MKL_THREADING_LAYER="${MKL_THREADING_LAYER:-TBB}"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
exec python -m patchbridge --open
