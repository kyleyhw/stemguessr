"""StemGuessr — music-guessing game built around Demucs-separated
stems sourced from a Spotify public playlist URL.

This package's runtime entry point is :func:`stemguessr.cli.main`, which is
re-exported here so the ``[project.scripts] stemguessr = "stemguessr:main"``
console-script wiring resolves it.
"""

from stemguessr.cli import __version__, main

__all__ = ["__version__", "main"]
