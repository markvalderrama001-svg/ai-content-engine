"""WordPress REST API client (Application Passwords) and an in-memory mock.

Credentials come only from environment variables:
  WP_BASE_URL       e.g. https://demo-blog.example.com
  WP_USER           the WordPress username that owns the Application Password
  WP_APP_PASSWORD   the Application Password (Users > Profile > Application Passwords)
"""
from __future__ import annotations

import base64
import copy
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Protocol


class WordPressError(RuntimeError):
    pass


class WordPressAPI(Protocol):
    def get_post(self, post_id: int) -> dict: ...
    def find_post_by_slug(self, slug: str) -> dict | None: ...
    def update_post(self, post_id: int, fields: dict) -> dict: ...


class WordPressClient:
    """Minimal client for the endpoints the pipeline needs. `context=edit` returns raw block content."""

    def __init__(self, base_url: str, user: str, app_password: str,
                 opener: Callable[..., object] | None = None, timeout: int = 60):
        if not (base_url and user and app_password):
            raise WordPressError("WP_BASE_URL, WP_USER and WP_APP_PASSWORD must be set")
        self.base = base_url.rstrip("/") + "/wp-json/wp/v2"
        token = base64.b64encode(f"{user}:{app_password}".encode()).decode()
        self._headers = {"Authorization": "Basic " + token, "Content-Type": "application/json",
                         "Accept": "application/json"}
        self._open = opener or urllib.request.urlopen
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "WordPressClient":
        return cls(os.environ.get("WP_BASE_URL", ""), os.environ.get("WP_USER", ""),
                   os.environ.get("WP_APP_PASSWORD", ""))

    def __repr__(self) -> str:  # never print credentials
        return f"WordPressClient({self.base!r})"

    def _call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=self._headers, method=method)
        try:
            with self._open(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise WordPressError(f"{method} {path} -> HTTP {exc.code}") from exc

    def get_post(self, post_id: int) -> dict:
        return self._call("GET", f"/posts/{int(post_id)}?context=edit")

    def find_post_by_slug(self, slug: str) -> dict | None:
        found = self._call("GET", f"/posts?slug={urllib.parse.quote(slug)}&context=edit&status=publish")
        return found[0] if found else None

    def update_post(self, post_id: int, fields: dict) -> dict:
        allowed = {"content"}  # content-only updates: title, slug, date and status are never sent
        if set(fields) - allowed:
            raise WordPressError(f"refusing to update fields other than content: {sorted(set(fields) - allowed)}")
        return self._call("POST", f"/posts/{int(post_id)}", fields)


class MockWordPress:
    """In-memory WordPress with the same interface, plus fault injection for demos and tests."""

    def __init__(self, posts: list[dict], site: str = "https://demo-blog.example.com"):
        self.site = site
        self.posts: dict[int, dict] = {}
        for p in posts:
            self.posts[p["id"]] = {
                "id": p["id"], "slug": p["slug"], "status": p.get("status", "publish"),
                "date": p["date"], "modified": p.get("modified", p["date"]),
                "title": {"raw": p["title"]}, "content": {"raw": p["content"]},
                "link": f"{site}/blog/{p['slug']}/",
            }
        self.writes: list[tuple[int, dict]] = []
        self.before_update: Callable[[int], None] | None = None   # hook, e.g. assert backup exists
        self.tamper: Callable[[dict], None] | None = None         # hook, e.g. simulate a slug change
        self._clock = dt.datetime(2026, 10, 25, 9, 0, 0)

    def get_post(self, post_id: int) -> dict:
        if post_id not in self.posts:
            raise WordPressError(f"GET /posts/{post_id} -> HTTP 404")
        return copy.deepcopy(self.posts[post_id])

    def find_post_by_slug(self, slug: str) -> dict | None:
        for p in self.posts.values():
            if p["slug"] == slug:
                return copy.deepcopy(p)
        return None

    def edit_live(self, post_id: int, new_content: str) -> None:
        """Simulate someone editing the live post in wp-admin."""
        self.posts[post_id]["content"]["raw"] = new_content
        self._tick(post_id)

    def update_post(self, post_id: int, fields: dict) -> dict:
        if self.before_update:
            self.before_update(post_id)
        self.writes.append((post_id, copy.deepcopy(fields)))
        post = self.posts[post_id]
        if "content" in fields:
            post["content"]["raw"] = fields["content"]
        self._tick(post_id)
        if self.tamper:
            self.tamper(post)
        return copy.deepcopy(post)

    def _tick(self, post_id: int) -> None:
        self._clock += dt.timedelta(seconds=7)
        self.posts[post_id]["modified"] = self._clock.isoformat()
