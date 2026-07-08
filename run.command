#!/bin/bash
# ============================================================
# StemGuessr one-click launcher for macOS (and Linux).
#
# Double-click in Finder (macOS) or run from a terminal.
#
# 1. Installs uv (the Python package manager) if it is missing.
# 2. Starts the StemGuessr server; the game opens in the default
#    browser automatically once the server is ready.
#
# The first run downloads the Python toolchain and dependencies
# (~2-3 GB, mostly PyTorch) plus ~250 MB of Demucs model weights.
# Subsequent runs start in seconds. Everything runs and stays on
# this machine; nothing is uploaded anywhere.
#
# macOS note: the first time you double-click this file, macOS may
# block it ("unidentified developer"). If so, Control-click the file
# once, choose Open, then Open again. This is a one-time approval.
# ============================================================
set -e
cd "$(dirname "$0")"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv not found - installing it now (one-time, a few MB)..."
    if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
        echo "Failed to install uv. See https://docs.astral.sh/uv/ for manual installation."
        read -r -p "Press Return to close. "
        exit 1
    fi
    # The installer places uv in ~/.local/bin, which a fresh shell has not
    # yet added to PATH; extend PATH for this session so `uv` resolves now.
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "Starting StemGuessr... the browser opens when the server is ready."
echo "(The first run may take several minutes while dependencies download.)"
uv run --no-dev stemguessr serve
