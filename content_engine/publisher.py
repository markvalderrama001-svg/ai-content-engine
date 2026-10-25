"""Safe publisher: backup -> assert -> drift check -> update -> verify -> log.

The same controls you would want on a journal-entry import:
1. Read the live record and write a backup of it to disk BEFORE anything else.
2. Assert it is the record we think it is (slug) and in the state we expect (published).
3. Drift check: if the live content differs from the snapshot the pipeline worked
   from, someone changed it since. Abort; never overwrite an edit we have not seen.
4. Dry-run by default. Only `dry_run=False` (CLI `--publish`) sends a write.
5. Update content only. Title, slug, date and status are never sent.
6. Verify the response: slug, status, title and date unchanged, content equals what we sent.
   A mismatch is reported with the backup path to restore from.
7. Append every outcome (including aborts and dry runs) to a JSON publish log.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .wordpress import WordPressAPI, WordPressError

OK, DRY_RUN = "OK", "DRY_RUN"
ABORT_ASSERT, ABORT_DRIFT = "ABORT_ASSERT", "ABORT_DRIFT"
VERIFY_FAILED, ERROR = "VERIFY_FAILED", "ERROR"


@dataclass
class PublishResult:
    slug: str
    id: int
    status: str
    mode: str
    reason: str = ""
    backup: str = ""
    live_changed_since_snapshot: bool | None = None
    checks: dict = field(default_factory=dict)
    modified: str = ""
    link: str = ""
    scores: dict = field(default_factory=dict)
    at: str = ""

    @property
    def ok(self) -> bool:
        return self.status in (OK, DRY_RUN)


class SafePublisher:
    def __init__(self, client: WordPressAPI, backup_dir: Path, log_path: Path, dry_run: bool = True,
                 mode_label: str | None = None):
        self.client = client
        self.backup_dir = Path(backup_dir)
        self.log_path = Path(log_path)
        self.dry_run = dry_run
        self.mode = mode_label or ("dry-run" if dry_run else "publish")

    def publish(self, *, post_id: int, slug: str, snapshot: dict, new_content: str,
                scores: dict | None = None) -> PublishResult:
        res = PublishResult(slug=slug, id=post_id, status=ERROR, mode=self.mode, scores=scores or {})
        try:
            self._publish(res, post_id, slug, snapshot, new_content)
        except (WordPressError, OSError, KeyError) as exc:
            res.status, res.reason = ERROR, f"{type(exc).__name__}: {exc}"
        res.at = dt.datetime.now().isoformat(timespec="seconds")
        self._log(res)
        return res

    def _publish(self, res: PublishResult, post_id: int, slug: str, snapshot: dict, new_content: str) -> None:
        live = self.client.get_post(post_id)

        # 1. Backup first, before any assertion can short-circuit and before any write.
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
        backup = self.backup_dir / f"{slug}.prepublish.{stamp}.json"
        backup.write_text(json.dumps(live, ensure_ascii=False, indent=1), encoding="utf-8")
        res.backup = backup.as_posix()
        res.link = live.get("link", "")

        # 2. Identity and state assertions.
        if live.get("slug") != slug or live.get("status") != "publish":
            res.status = ABORT_ASSERT
            res.reason = f"expected slug={slug} status=publish, live has slug={live.get('slug')} status={live.get('status')}"
            return

        # 3. Drift check against the snapshot the pipeline worked from.
        drift = live["content"]["raw"] != snapshot["content"]["raw"]
        res.live_changed_since_snapshot = drift
        if drift:
            res.status = ABORT_DRIFT
            res.reason = "live content changed since the pipeline snapshot; re-run on the current version"
            return

        # 4. Dry run stops here: everything above was read-only.
        if self.dry_run:
            res.status, res.reason = DRY_RUN, "all pre-write checks passed; no write sent (use --publish)"
            return

        # 5. Content-only update.
        updated = self.client.update_post(post_id, {"content": new_content})

        # 6. Verify nothing but content changed.
        res.checks = {
            "slug": updated.get("slug") == live["slug"],
            "status": updated.get("status") == live["status"],
            "title": updated.get("title", {}).get("raw") == live["title"]["raw"],
            "date": updated.get("date") == live["date"],
            "content": updated.get("content", {}).get("raw") == new_content,
        }
        res.modified = updated.get("modified", "")
        if all(res.checks.values()):
            res.status, res.reason = OK, "updated and verified"
        else:
            bad = [k for k, v in res.checks.items() if not v]
            res.status = VERIFY_FAILED
            res.reason = f"post-update mismatch on {', '.join(bad)}; restore from {res.backup}"

    def _log(self, res: PublishResult) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        entries = []
        if self.log_path.exists():
            entries = json.loads(self.log_path.read_text(encoding="utf-8") or "[]")
        entry = asdict(res)
        entry["ok"] = res.ok
        entries.append(entry)
        self.log_path.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
