"""HTTP for the optional online services (dofusdb.fr, Google Sheets), stdlib only."""
from __future__ import annotations

import http.client
import time
import urllib.request

from . import __version__

USER_AGENT = f"DofusPetMerch/{__version__} (+https://github.com/ptruebadev-oss)"
# Everything open_url (and reading its body) can raise when the network or the server fails.
# URLError and HTTPError are OSErrors; a connection cut mid-body raises an HTTPException.
NETWORK_ERRORS = (OSError, ValueError, http.client.HTTPException)


def open_url(req: urllib.request.Request, timeout: float) -> tuple[bytes, str]:
    """(body, content type). The single network seam: tests replace it.

    urlopen follows redirects, which turns the Apps Script POST into the GET that serves
    its response."""
    if not req.has_header("User-agent"):
        req.add_header("User-Agent", USER_AGENT)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.headers.get("Content-Type", "")


class Backoff:
    """After a network failure, automatic requests to that service wait a few minutes so the
    hotkey stays fast offline. One instance per service."""

    def __init__(self, seconds: float = 300):
        self.seconds = seconds
        self.until = 0.0

    @property
    def active(self) -> bool:
        return time.time() < self.until

    def trip(self) -> None:
        self.until = time.time() + self.seconds

    def reset(self) -> None:
        self.until = 0.0
