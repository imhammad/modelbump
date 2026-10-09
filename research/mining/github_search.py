"""A small client for GitHub's commit-search API.

It does three things a research miner needs:

- caches every raw response on disk, so a run can stop and resume, and every
  number in the paper can be traced back to the exact response it came from;
- waits when GitHub says the rate limit is reached, as GitHub's docs ask;
- spaces requests out to stay under 30 search requests per minute.
"""

import hashlib
import json
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

SEARCH_URL = "https://api.github.com/search/commits"
# GitHub requires a User-Agent that names the app, and refuses some requests without one.
USER_AGENT = "modelbump-research-miner (+https://github.com/imhammad/modelbump)"
PER_PAGE = 100
MAX_RESULTS = 1000  # GitHub returns at most 1,000 results for any one search.


class RateLimitError(RuntimeError):
    """Raised when GitHub keeps refusing requests after every retry."""


class CommitSearchClient:
    """Search commits, with a disk cache and rate-limit handling."""

    def __init__(
        self,
        cache_dir: Path,
        token: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.time,
        min_interval: float = 2.1,
        max_retries: int = 5,
    ) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": USER_AGENT,
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(headers=headers, transport=transport, timeout=30.0)
        self._sleep = sleep
        self._clock = clock
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_request = float("-inf")
        self.requests_made = 0
        self.cache_hits = 0

    def search(self, query: str, page: int = 1) -> dict[str, Any]:
        """Return one page of results for ``query``, from the cache if possible."""
        path = self.cache_dir / f"{_cache_key(query, page)}.json"
        if path.exists():
            self.cache_hits += 1
            record: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            cached: dict[str, Any] = record["response"]
            return cached
        response = self._fetch(query, page)
        record = {
            "query": query,
            "page": page,
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "response": response,
        }
        # Write to a temporary file first, so an interrupted run never leaves a
        # half-written cache entry behind.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record), encoding="utf-8")
        tmp.replace(path)
        return response

    def _fetch(self, query: str, page: int) -> dict[str, Any]:
        params: dict[str, str | int] = {
            "q": query,
            "per_page": PER_PAGE,
            "page": page,
            "sort": "committer-date",
            "order": "asc",
        }
        for attempt in range(self._max_retries + 1):
            self._throttle()
            response = self._http.get(SEARCH_URL, params=params)
            self.requests_made += 1
            if _is_rate_limited(response):
                wait = _wait_seconds(response, attempt, self._clock())
                print(
                    f"GitHub refused the search ({response.status_code}: {_message(response)}); "
                    f"waiting {wait:.0f}s ...",
                    file=sys.stderr,
                )
                self._sleep(wait)
                continue
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            return data
        raise RateLimitError(f"GitHub kept refusing the search for {query!r} (page {page})")

    def _throttle(self) -> None:
        wait = self._last_request + self._min_interval - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last_request = self._clock()


def _cache_key(query: str, page: int) -> str:
    return hashlib.sha256(f"{query}\n{page}".encode()).hexdigest()


def _is_rate_limited(response: httpx.Response) -> bool:
    """True only for GitHub's rate-limit refusals, not for other 403 errors."""
    if response.status_code not in (403, 429):
        return False
    return (
        "retry-after" in response.headers
        or response.headers.get("x-ratelimit-remaining") == "0"
        or "rate limit" in response.text.lower()
    )


def _message(response: httpx.Response) -> str:
    """GitHub's error message, or the start of the body if it is not JSON."""
    try:
        return str(response.json().get("message", ""))
    except ValueError:
        return response.text[:200]


def _wait_seconds(response: httpx.Response, attempt: int, now: float) -> float:
    """How long to wait after a 403/429, following GitHub's rate-limit docs."""
    retry_after = response.headers.get("retry-after")
    if retry_after is not None:
        return float(retry_after)
    reset = response.headers.get("x-ratelimit-reset")
    if response.headers.get("x-ratelimit-remaining") == "0" and reset is not None:
        return max(float(reset) - now, 0.0) + 1.0
    return 60.0 * 2.0**attempt
