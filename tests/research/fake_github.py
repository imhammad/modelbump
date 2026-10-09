"""A fake GitHub commit-search API for tests. No network is used."""

import re
from datetime import date
from typing import Any

import httpx

QUERY = re.compile(r'^"(?P<id>[^"]+)" committer-date:(?P<start>[\d-]+)\.\.(?P<end>[\d-]+)$')


def make_item(
    sha: str, model_id: str, day: date, *, fork: bool = False, repo: str = "acme/app"
) -> dict[str, Any]:
    return {
        "sha": sha,
        "html_url": f"https://github.com/{repo}/commit/{sha}",
        "repository": {"full_name": repo, "fork": fork},
        "commit": {
            "message": f"Migrate from {model_id}",
            "committer": {"date": f"{day.isoformat()}T12:00:00Z"},
        },
    }


class FakeGitHub:
    """Serves search results from a list of (model_id, item) pairs."""

    def __init__(self, commits: list[tuple[str, dict[str, Any]]]) -> None:
        self.commits = commits
        self.calls: list[tuple[str, int]] = []
        self.refusals: list[httpx.Response] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.refusals:
            return self.refusals.pop(0)
        q = request.url.params["q"]
        page = int(request.url.params["page"])
        per_page = int(request.url.params["per_page"])
        self.calls.append((q, page))
        m = QUERY.match(q)
        assert m, f"unexpected query {q!r}"
        start, end = date.fromisoformat(m["start"]), date.fromisoformat(m["end"])
        hits = [
            item
            for model_id, item in self.commits
            if model_id == m["id"]
            and start <= date.fromisoformat(item["commit"]["committer"]["date"][:10]) <= end
        ]
        hits.sort(key=lambda i: i["commit"]["committer"]["date"])
        visible = hits[:1000]
        items = visible[(page - 1) * per_page : page * per_page]
        return httpx.Response(
            200, json={"total_count": len(hits), "incomplete_results": False, "items": items}
        )

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
