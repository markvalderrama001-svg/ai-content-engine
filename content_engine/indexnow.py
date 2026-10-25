"""IndexNow URL submission (Bing, Copilot and other IndexNow engines). Dry-run by default.

Environment:
  INDEXNOW_KEY        your IndexNow key (also hosted at https://<host>/<key>.txt)
  INDEXNOW_ENDPOINT   optional, defaults to https://api.indexnow.org/indexnow

Controls: host allowlist (every URL must be on the configured site), batching,
bounded retries with exponential back-off, and a per-batch result list.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

DEFAULT_ENDPOINT = "https://api.indexnow.org/indexnow"


@dataclass
class BatchResult:
    urls: list[str]
    status: str        # DRY_RUN | OK | FAILED | REJECTED
    detail: str = ""


class IndexNowSubmitter:
    def __init__(self, host: str, key: str = "", *, endpoint: str = DEFAULT_ENDPOINT, dry_run: bool = True,
                 batch_size: int = 100, max_retries: int = 3,
                 transport: Callable[[urllib.request.Request], int] | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.host = host
        self.key = key
        self.endpoint = endpoint
        self.dry_run = dry_run
        self.batch_size = batch_size
        self.max_retries = max_retries
        self._send = transport or self._urlopen
        self._sleep = sleep

    @classmethod
    def from_env(cls, host: str, dry_run: bool = True) -> "IndexNowSubmitter":
        return cls(host, os.environ.get("INDEXNOW_KEY", ""),
                   endpoint=os.environ.get("INDEXNOW_ENDPOINT", DEFAULT_ENDPOINT), dry_run=dry_run)

    @staticmethod
    def _urlopen(req: urllib.request.Request) -> int:
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code

    def submit(self, urls: list[str]) -> list[BatchResult]:
        allowed = [u for u in urls if urlparse(u).hostname == self.host]
        rejected = [u for u in urls if u not in allowed]
        results = [BatchResult(rejected, "REJECTED", f"not on allowlisted host {self.host}")] if rejected else []
        for i in range(0, len(allowed), self.batch_size):
            batch = allowed[i: i + self.batch_size]
            if self.dry_run:
                results.append(BatchResult(batch, "DRY_RUN", f"would POST {len(batch)} URL(s) to {self.endpoint}"))
                continue
            if not self.key:
                results.append(BatchResult(batch, "FAILED", "INDEXNOW_KEY not set"))
                continue
            results.append(self._post(batch))
        return results

    def _post(self, batch: list[str]) -> BatchResult:
        body = json.dumps({"host": self.host, "key": self.key, "urlList": batch}).encode()
        last = ""
        for attempt in range(self.max_retries):
            req = urllib.request.Request(self.endpoint, data=body, method="POST",
                                         headers={"Content-Type": "application/json; charset=utf-8"})
            code = self._send(req)
            if code in (200, 202):
                return BatchResult(batch, "OK", f"HTTP {code}")
            last = f"HTTP {code}"
            if code in (400, 403, 422):   # not retryable: bad request, key not verified, URL/host mismatch
                break
            self._sleep(2 ** attempt)
        return BatchResult(batch, "FAILED", last)
