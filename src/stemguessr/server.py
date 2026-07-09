"""HTTP server for StemGuessr.

Hosts the static frontend, serves the cache contents (manifest.json, stems/*,
previews/*) under the same origin, and exposes ``POST /api/ingest`` so the
browser can kick off an ingest run without dropping back to the terminal,
plus ``POST /api/reset`` so it can clear the cache and return to the
playlist form.

A single ingest is allowed at a time; concurrent ``/api/ingest`` requests
return HTTP 409 Conflict, as do ``/api/reset`` requests while an ingest is
in flight. Ingest runs in a daemon thread that writes the manifest
progressively, exactly as the CLI's ``ingest`` command does.

Public API: :func:`serve_forever`.
"""

from __future__ import annotations

import http.server
import json
import shutil
import socketserver
import threading
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

from stemguessr.manifest import MANIFEST_FILENAME

# The frontend ships inside the package (src/stemguessr/web/), so the wheel
# is self-contained and `uvx stemguessr serve` works without a repo checkout.
# Wheels are always installed as real directories (never run zipped), so a
# plain Path relative to __file__ is sufficient — no importlib.resources
# machinery needed.
DEFAULT_WEB_DIR = Path(__file__).parent / "web"


# Upper bound on how long the reset endpoint waits for a cancelled ingest to
# stop. Cancellation is checked between tracks, so the wait is at most the
# time to finish the track in flight — a single Demucs separation, ~5-15 s on
# CPU for 4 stems and more for 6. 60 s leaves generous margin; if it is ever
# exceeded the endpoint reports 503 and the user can retry (by which point the
# thread has almost certainly finished).
_CANCEL_JOIN_TIMEOUT = 60.0


class _IngestState:
    """Thread-safe single-flight tracker for the in-flight ingest, if any,
    with cooperative cancellation.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        # Set to request cancellation of the current run; replaced with a
        # fresh (clear) event each time a new ingest starts.
        self._cancel = threading.Event()

    def try_start(self, target: Callable[[], None]) -> bool:
        """Start ``target`` in a daemon thread iff no ingest is currently
        running. Returns True on a successful spawn, False if rejected.

        A fresh cancellation event is installed before the thread starts, so
        ``should_cancel`` reflects only the run being started.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            self._cancel = threading.Event()
            t = threading.Thread(target=target, daemon=True)
            self._thread = t
        t.start()
        return True

    def is_busy(self) -> bool:
        """True iff an ingest thread is currently running."""
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def should_cancel(self) -> bool:
        """Poll target for the current run; passed to ``run_ingest_pipeline``."""
        return self._cancel.is_set()

    def cancel_and_join(self, timeout: float) -> bool:
        """Request cancellation and wait for the ingest thread to terminate.

        Returns True if no ingest was running or it stopped within ``timeout``
        (so callers may safely touch the cache), False if it is still alive
        after the timeout. The join runs outside the lock so concurrent
        ``is_busy`` calls do not block.
        """
        with self._lock:
            thread = self._thread
            self._cancel.set()
        if thread is None or not thread.is_alive():
            return True
        thread.join(timeout)
        return not thread.is_alive()


def _make_handler(
    *,
    web_dir: Path,
    cache_dir: Path,
    state: _IngestState,
    log: Callable[[str], None],
) -> type[http.server.SimpleHTTPRequestHandler]:
    """Build a SimpleHTTPRequestHandler subclass closed over the directories
    and shared state. We use a closure rather than handler-instance attrs
    because SimpleHTTPRequestHandler instantiates the class per request.
    """

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, directory=str(cache_dir), **kwargs)

        # --- routing -----------------------------------------------------

        def translate_path(self, path: str) -> str:
            # Strip query / fragment (SimpleHTTPRequestHandler already does
            # this via posixpath logic, but our overrides need the clean form).
            clean = path.split("?", 1)[0].split("#", 1)[0]
            # Frontend assets come from web_dir; everything else (manifest,
            # stems/*, previews/*) is served out of cache_dir.
            if clean in ("/", "/index.html"):
                return str(web_dir / "index.html")
            if clean in ("/styles.css", "/game.js", "/favicon.svg"):
                return str(web_dir / clean.lstrip("/"))
            return super().translate_path(path)

        def do_POST(self) -> None:
            if self.path == "/api/ingest":
                self._handle_ingest()
            elif self.path == "/api/reset":
                self._handle_reset()
            else:
                self._json_error(404, f"unknown endpoint {self.path!r}")

        # --- /api/ingest -------------------------------------------------

        def _handle_ingest(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            try:
                raw = self.rfile.read(length).decode("utf-8")
                payload = json.loads(raw)
                playlist_url = payload["playlist_url"]
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as e:
                self._json_error(400, f"bad request: {e}")
                return

            n_stems = int(payload.get("n_stems", 4))
            limit_raw = payload.get("limit")
            limit = int(limit_raw) if limit_raw not in (None, "") else None

            def _run() -> None:
                from stemguessr.cli import run_ingest_pipeline  # avoid cycle

                try:
                    run_ingest_pipeline(
                        playlist_url,
                        cache_dir,
                        n_stems=n_stems,
                        limit=limit,
                        log=log,
                        should_cancel=state.should_cancel,
                    )
                except Exception as exc:  # noqa: BLE001
                    log(f"[server] ingest failed: {exc}")

            if not state.try_start(_run):
                self._json_error(409, "ingest already running")
                return

            self._json_response(202, {"status": "started"})

        # --- /api/reset --------------------------------------------------

        def _handle_reset(self) -> None:
            """Cancel any in-flight ingest, then clear the cache (manifest +
            stems + previews).

            The cancel-then-join before deleting is the crucial ordering: it
            guarantees the ingest thread has run its ``finally`` (its last
            manifest write) and terminated before we delete, so it cannot
            re-create files under us. A stalled separation that outruns the
            join budget yields 503 rather than a partial delete; the user
            retries. (A concurrent ``/api/ingest`` landing after the join
            could still race the delete, but that needs two clients against a
            single-user localhost server, so we accept it rather than add a
            global lock.)
            """
            if not state.cancel_and_join(_CANCEL_JOIN_TIMEOUT):
                self._json_error(
                    503, "ingest is still stopping — try reset again shortly"
                )
                return
            try:
                (cache_dir / MANIFEST_FILENAME).unlink(missing_ok=True)
                for sub in ("stems", "previews"):
                    subdir = cache_dir / sub
                    if subdir.exists():
                        shutil.rmtree(subdir)
            except OSError as e:
                self._json_error(500, f"reset failed: {e}")
                return
            log("[server] cache reset — manifest, stems, previews deleted")
            self._json_response(200, {"status": "reset"})

        # --- response helpers --------------------------------------------

        def _json_response(self, status: int, body: dict[str, Any]) -> None:
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _json_error(self, status: int, msg: str) -> None:
            self._json_response(status, {"error": msg})

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            # Keep noise low; only log non-200s.
            try:
                code = int(args[1])
            except (IndexError, ValueError, TypeError):
                code = 0
            if code and code >= 400:
                log(f"[http] {self.address_string()} {format % args}")

    return Handler


# A threaded TCPServer so an in-flight long-running fetch (e.g. the playlist
# embed page) does not block subsequent requests. Each connection runs in
# its own daemon thread.
class _ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve_forever(
    *,
    cache_dir: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    web_dir: Path = DEFAULT_WEB_DIR,
    log: Callable[[str], None] = print,
    open_browser: bool = True,
) -> None:
    """Run the StemGuessr server until interrupted (Ctrl-C).

    Args:
        cache_dir: Where ingest writes; also served as the static root for
            ``manifest.json``, ``stems/``, ``previews/``.
        host: Bind address. Default ``127.0.0.1`` (localhost only).
        port: TCP port.
        web_dir: Source directory for ``index.html``, ``styles.css``,
            ``game.js``. Defaults to the package's bundled ``web/`` folder.
        log: Sink for one-line progress messages.
        open_browser: Open the game in the default browser once the server
            socket is bound. This is the zero-instruction path for the
            ``run.bat`` / ``uvx`` distribution; pass False (CLI:
            ``--no-browser``) for headless or development use.
    """
    state = _IngestState()
    handler_cls = _make_handler(
        web_dir=web_dir,
        cache_dir=cache_dir,
        state=state,
        log=log,
    )
    with _ThreadedHTTPServer((host, port), handler_cls) as httpd:
        if open_browser:
            # The socket is bound and listening as soon as the server object
            # exists — a browser connecting now queues in the listen backlog
            # and is served the moment serve_forever() starts, so no
            # port-polling is needed.
            webbrowser.open(f"http://{host}:{port}/")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            log("shutting down...")
