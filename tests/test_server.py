"""Tests for stemguessr.server — routing and the ``/api/reset`` endpoint.

The server is exercised over real HTTP on an ephemeral port (port 0 →
OS-assigned): ``_make_handler`` is closed over a ``tmp_path`` cache dir and
a fresh ``_IngestState``, served by the same ``_ThreadedHTTPServer`` used in
production. No real ingest is ever invoked; a running ingest is modelled by a
real thread that polls ``state.should_cancel`` exactly as the pipeline does
between tracks, so the cancellation path is exercised through the same lock
and event the production code uses (rather than a monkeypatched stub).
"""

from __future__ import annotations

import http.client
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from stemguessr.server import (
    DEFAULT_WEB_DIR,
    _IngestState,
    _make_handler,
    _ThreadedHTTPServer,
)


class _RunningServer:
    """A live server bound to 127.0.0.1:<ephemeral> plus its shared state."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.state = _IngestState()
        handler = _make_handler(
            web_dir=DEFAULT_WEB_DIR,
            cache_dir=cache_dir,
            state=self.state,
            log=lambda _msg: None,
        )
        self.httpd = _ThreadedHTTPServer(("127.0.0.1", 0), handler)
        self.port: int = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self._thread.start()

    def request(self, method: str, path: str) -> tuple[int, str]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path)
            resp = conn.getresponse()
            return resp.status, resp.read().decode("utf-8")
        finally:
            conn.close()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server(tmp_path: Path) -> Iterator[_RunningServer]:
    s = _RunningServer(tmp_path)
    try:
        yield s
    finally:
        s.close()


def _seed_cache(cache_dir: Path) -> list[Path]:
    """Populate the cache with the three artefact kinds reset must delete.

    One file of each kind (manifest, a stem WAV, a preview) is the minimal
    set that distinguishes "deleted the whole cache" from "deleted only one
    directory".
    """
    manifest = cache_dir / "manifest.json"
    manifest.write_text('{"version": 1}', encoding="utf-8")
    stem = cache_dir / "stems" / "trackid" / "drums.wav"
    stem.parent.mkdir(parents=True)
    stem.write_bytes(b"\x00" * 44)
    preview = cache_dir / "previews" / "trackid.mp3"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"\x00" * 16)
    return [manifest, stem, preview]


class TestReset:
    def test_reset_clears_cache(self, server: _RunningServer) -> None:
        seeded = _seed_cache(server.cache_dir)
        status, body = server.request("POST", "/api/reset")
        assert status == 200
        assert "reset" in body
        for path in seeded:
            assert not path.exists(), f"survived reset: {path}"
        assert not (server.cache_dir / "stems").exists()
        assert not (server.cache_dir / "previews").exists()

    def test_reset_on_empty_cache_is_ok(self, server: _RunningServer) -> None:
        """Reset must be idempotent: a second (or premature) click returns
        200 rather than erroring on already-missing files.
        """
        status, _body = server.request("POST", "/api/reset")
        assert status == 200

    def test_reset_cancels_running_ingest(self, server: _RunningServer) -> None:
        """Reset must cancel an in-flight ingest, wait for it to stop, then
        clear the cache — not refuse. The fake ingest models the pipeline's
        cooperative between-track cancellation by polling ``should_cancel``.
        """
        seeded = _seed_cache(server.cache_dir)

        started = threading.Event()
        stopped = threading.Event()

        def _fake_ingest() -> None:
            started.set()
            # Cooperative cancellation, exactly as run_ingest_pipeline does:
            # spin until the shared cancel flag is set, then return.
            while not server.state.should_cancel():
                time.sleep(0.01)
            stopped.set()

        assert server.state.try_start(_fake_ingest)
        assert started.wait(timeout=5)

        status, body = server.request("POST", "/api/reset")
        assert status == 200
        assert "reset" in body
        # The fake ingest observed the cancel and returned before the delete.
        assert stopped.is_set()
        assert not server.state.is_busy()
        for path in seeded:
            assert not path.exists(), f"survived reset: {path}"

    def test_reset_times_out_if_ingest_wont_stop(self, server: _RunningServer) -> None:
        """If a run ignores cancellation past the join budget, reset reports
        503 and leaves the cache intact rather than deleting under a live
        writer. A zero timeout is monkeypatched in so the test is instant.
        """
        import stemguessr.server as server_mod

        monkey = pytest.MonkeyPatch()
        monkey.setattr(server_mod, "_CANCEL_JOIN_TIMEOUT", 0.0)
        seeded = _seed_cache(server.cache_dir)

        started = threading.Event()
        release = threading.Event()

        def _stuck_ingest() -> None:
            started.set()
            release.wait()  # never observes cancellation

        try:
            assert server.state.try_start(_stuck_ingest)
            assert started.wait(timeout=5)
            status, body = server.request("POST", "/api/reset")
            assert status == 503
            assert "stopping" in body
            for path in seeded:
                assert path.exists(), f"deleted despite 503: {path}"
        finally:
            release.set()
            monkey.undo()


class TestRouting:
    def test_unknown_post_endpoint_is_404(self, server: _RunningServer) -> None:
        status, _body = server.request("POST", "/api/nonsense")
        assert status == 404

    def test_root_serves_bundled_frontend(self, server: _RunningServer) -> None:
        """GET / must serve the index.html bundled inside the package —
        the regression guard for the web/-into-wheel packaging move.
        """
        status, body = server.request("GET", "/")
        assert status == 200
        assert "StemGuessr" in body

    def test_favicon_served(self, server: _RunningServer) -> None:
        """GET /favicon.svg must serve the bundled icon (200), not fall
        through to the cache dir and 404. Guards both the route and the
        icon's inclusion in the wheel.
        """
        status, body = server.request("GET", "/favicon.svg")
        assert status == 200
        assert "<svg" in body
