#!/bin/bash
# ============================================================
# StemGuessr uninstaller for macOS (and Linux).
#
# Removes what StemGuessr put on this machine. Two tiers:
#   1. App-local: the .venv and the ingested cache in this folder
#      (always removed).
#   2. Shared downloads outside this folder: uv's package cache and
#      the Demucs model weights, ~2-3 GB (removed only if you agree).
#
# After running, delete this folder to finish. uv itself is left
# installed unless you remove it manually (see the note at the end).
# ============================================================
cd "$(dirname "$0")"

echo "StemGuessr uninstaller"
echo

echo "Removing local environment (.venv) and ingested cache (cache/)..."
rm -rf .venv cache

echo
echo "StemGuessr also downloaded ~2-3 GB of shared files OUTSIDE this folder:"
echo "  - Python dependencies in uv's cache"
echo "  - Demucs AI model weights (~/.cache/torch)"
echo "Remove these too? Choose yes only if you do not use uv or PyTorch"
echo "for anything else on this machine."
read -r -p "Remove shared downloads? [y/N] " ans
case "$ans" in
    [yY]*)
        if command -v uv >/dev/null 2>&1; then
            uv cache clean || true
        fi
        rm -rf "$HOME/.cache/torch"
        echo "Shared downloads removed."
        ;;
    *)
        echo "Left shared downloads in place."
        ;;
esac

echo
echo "Done. To finish, delete this StemGuessr folder."
echo "To remove uv itself as well, run:  uv self uninstall"
read -r -p "Press Return to close. "
