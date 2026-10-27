"""A content-addressed cache of model answers, in one SQLite file (ADR 0037).

The key is a SHA-256 hash of everything that can change an answer: the model,
the full message list, the sampling options and the sample number. Asking the
same thing twice reads the first answer back instead of calling the model, so
experiments can be re-run for free and give the same numbers.
"""

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from modelbump.runner.types import ChatRequest, ChatResult

# Bump this when the key recipe changes, so old entries are never misread.
# 2: adds reasoning_effort and model_version (ADR 0039).
KEY_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    key TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    text TEXT NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    finish_reason TEXT NOT NULL,
    created_at TEXT NOT NULL
)
"""


def default_cache_path() -> Path:
    """`$MODELBUMP_CACHE_DIR/responses.sqlite`, else the user's cache folder."""
    folder = os.environ.get("MODELBUMP_CACHE_DIR")
    if folder:
        return Path(folder) / "responses.sqlite"
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "modelbump" / "responses.sqlite"


def cache_key(request: ChatRequest) -> str:
    """The SHA-256 hex digest of the request's canonical JSON form."""
    payload = {
        "v": KEY_VERSION,
        "model": request.model,
        "messages": [[m.role, m.content] for m in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "seed": request.seed,
        "sample": request.sample,
        "reasoning_effort": request.reasoning_effort,
        "model_version": request.model_version,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CacheStats:
    """What the cache holds."""

    path: Path
    entries: int
    output_tokens: int
    size_bytes: int


class ResponseCache:
    """Stores successful answers by request hash. Errors are never cached."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else default_cache_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path)
        # WAL lets two processes read and write the same cache safely.
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(_SCHEMA)
        self._db.commit()

    def get(self, request: ChatRequest) -> ChatResult | None:
        """The stored answer for this request, or None."""
        row = self._db.execute(
            "SELECT text, input_tokens, output_tokens, finish_reason FROM responses WHERE key = ?",
            (cache_key(request),),
        ).fetchone()
        if row is None:
            return None
        text, input_tokens, output_tokens, finish_reason = row
        return ChatResult(
            text=text,
            model=request.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason=finish_reason,
            attempts=0,
            seconds=0.0,
            cached=True,
        )

    def put(self, request: ChatRequest, result: ChatResult) -> None:
        """Store an answer. A second answer for the same request replaces the first."""
        self._db.execute(
            "INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                cache_key(request),
                request.model,
                result.text,
                result.input_tokens,
                result.output_tokens,
                result.finish_reason,
                datetime.now(UTC).isoformat(timespec="seconds"),
            ),
        )
        self._db.commit()

    def stats(self) -> CacheStats:
        """How many answers are stored, and how big the file is."""
        entries, tokens = self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(output_tokens), 0) FROM responses"
        ).fetchone()
        size = sum(p.stat().st_size for p in (self.path, Path(f"{self.path}-wal")) if p.exists())
        return CacheStats(self.path, entries, tokens, size)

    def clear(self) -> int:
        """Delete every stored answer. Returns how many were deleted."""
        deleted = self._db.execute("DELETE FROM responses").rowcount
        self._db.commit()
        self._db.execute("VACUUM")
        return deleted

    def close(self) -> None:
        self._db.close()
