"""Preview source lookup and download for ISRC-keyed 30-second audio clips.

Given an International Standard Recording Code (ISRC), this module retrieves
the corresponding 30-second preview from a public source and caches it on
disk. Two sources are queried in priority order:

1. **iTunes Search API** (preferred). Stable, Apple-promoted, returns 30 s AAC
   in an M4A container. Endpoint: ``https://itunes.apple.com/lookup``.
2. **Deezer API** (fallback). Returns 30 s 128 kbps MP3. Endpoint:
   ``https://api.deezer.com/track/isrc:{ISRC}``.

The first source returning a usable ``previewUrl`` (resp. ``preview``) is
downloaded and cached. Combined coverage is essentially complete for any track
with an ISRC on Spotify.

Public API:

* :func:`get_preview` — high-level: ISRC → cached file path (or None).
* :func:`lookup_itunes`, :func:`lookup_deezer` — single-source lookups for
  composition and testing.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

# --- Constants ---

ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"
DEEZER_LOOKUP_URL_TEMPLATE = "https://api.deezer.com/track/isrc:{isrc}"

DEFAULT_TIMEOUT: httpx.Timeout = httpx.Timeout(10.0, connect=5.0)
DEFAULT_RETRIES = 3
USER_AGENT = "stemguessr/0.1.0 (+https://github.com/kyleyhw/stemguessr)"

# Cap individual sleep at this many seconds, regardless of Retry-After header,
# so a hostile or buggy server cannot block ingest indefinitely.
_MAX_SLEEP_SECONDS = 30.0


# --- Exceptions ---


class SourceError(RuntimeError):
    """Raised when a preview source returns a malformed or unusable response."""


# --- Result type ---


@dataclass(frozen=True, slots=True)
class PreviewMatch:
    """A successful source lookup, prior to download.

    Attributes:
        isrc: The ISRC the lookup was performed for.
        source: ``"itunes"`` or ``"deezer"``.
        url: The remote preview URL to download.
        extension: ``"m4a"`` for iTunes, ``"mp3"`` for Deezer.
    """

    isrc: str
    source: str
    url: str
    extension: str


# --- Retry helper ---


def _request_with_retry(
    client: httpx.Client,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    max_retries: int = DEFAULT_RETRIES,
) -> httpx.Response:
    """GET a URL with exponential-backoff retry on transient failures.

    Retries on network errors and on HTTP 429 (Too Many Requests), respecting
    the ``Retry-After`` header when present (capped at ``_MAX_SLEEP_SECONDS``).
    Non-2xx, non-429 responses are raised immediately and not retried.

    Time delays use :func:`time.sleep`; tests should monkeypatch it.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            response = client.get(url, params=params)
            if response.status_code == 429:
                wait = float(response.headers.get("Retry-After", str(2**attempt)))
                time.sleep(min(wait, _MAX_SLEEP_SECONDS))
                continue
            response.raise_for_status()
            return response
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            last_exc = e
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("unreachable: max_retries was 0")


# --- Per-source lookups ---


def lookup_itunes(client: httpx.Client, isrc: str) -> PreviewMatch | None:
    """Look up an ISRC on the iTunes Search API.

    Returns None if iTunes has no record (or no ``previewUrl``) for the ISRC.

    Raises:
        SourceError: The endpoint returned non-JSON.
        httpx.HTTPStatusError: 5xx after retries exhausted.
    """
    response = _request_with_retry(
        client,
        ITUNES_LOOKUP_URL,
        params={"isrc": isrc, "entity": "song"},
    )
    try:
        data = response.json()
    except json.JSONDecodeError as e:
        raise SourceError(f"iTunes returned non-JSON for ISRC {isrc!r}") from e

    results = data.get("results") or []
    if not results:
        return None
    preview_url = results[0].get("previewUrl")
    if not preview_url:
        return None
    return PreviewMatch(
        isrc=isrc,
        source="itunes",
        url=preview_url,
        extension="m4a",
    )


def lookup_deezer(client: httpx.Client, isrc: str) -> PreviewMatch | None:
    """Look up an ISRC on Deezer's public API.

    Deezer signals a miss either by HTTP 4xx or by HTTP 200 with an
    ``error`` object in the JSON body; this function treats both as misses
    and returns None. 5xx responses propagate after retries.

    Returns None if Deezer has no record (or no ``preview`` URL) for the ISRC.

    Raises:
        SourceError: The endpoint returned non-JSON.
    """
    url = DEEZER_LOOKUP_URL_TEMPLATE.format(isrc=isrc)
    try:
        response = _request_with_retry(client, url)
    except httpx.HTTPStatusError as e:
        if e.response.status_code >= 500:
            raise
        return None  # 4xx → clean miss

    try:
        data = response.json()
    except json.JSONDecodeError as e:
        raise SourceError(f"Deezer returned non-JSON for ISRC {isrc!r}") from e

    if "error" in data:
        return None
    preview_url = data.get("preview")
    if not preview_url:
        return None
    return PreviewMatch(
        isrc=isrc,
        source="deezer",
        url=preview_url,
        extension="mp3",
    )


# --- Download ---


def _download(client: httpx.Client, url: str, dest: Path) -> None:
    """Stream-download ``url`` to ``dest`` atomically (temp file + rename).

    The destination's parent directory is created if missing. The temp file
    name is the destination plus a ``.tmp`` suffix; the rename is performed
    by :meth:`Path.replace`, which is atomic on the same filesystem.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with client.stream("GET", url) as response:
        response.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)
    tmp.replace(dest)


# --- Top-level public API ---


def get_preview(
    isrc: str,
    cache_dir: Path,
    *,
    client: httpx.Client | None = None,
) -> Path | None:
    """Return a path to a cached 30-second preview for ``isrc``.

    Cache layout::

        {cache_dir}/previews/{ISRC}.{m4a|mp3}

    On a cache hit, the existing file path is returned without any network
    activity. On a miss, sources are tried in order (iTunes, then Deezer);
    the first that returns a ``previewUrl`` is downloaded into the cache.

    Args:
        isrc: International Standard Recording Code, 12 chars.
        cache_dir: Root cache directory; ``previews/`` subdirectory is
            created on demand.
        client: Optional :class:`httpx.Client`. If omitted, an internal
            client is constructed for the call and closed before return.

    Returns:
        The local path of the cached preview, or ``None`` if no source has
        a preview for this ISRC.
    """
    previews_dir = cache_dir / "previews"

    # Cache hit?
    for ext in ("m4a", "mp3"):
        candidate = previews_dir / f"{isrc}.{ext}"
        if candidate.exists():
            return candidate

    owns_client = client is None
    if client is None:
        client = httpx.Client(
            timeout=DEFAULT_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )
    try:
        for source_fn in (lookup_itunes, lookup_deezer):
            match = source_fn(client, isrc)
            if match is None:
                continue
            dest = previews_dir / f"{isrc}.{match.extension}"
            _download(client, match.url, dest)
            return dest
        return None
    finally:
        if owns_client:
            client.close()
