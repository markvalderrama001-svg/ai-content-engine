"""Publisher safety: dry run never writes, drift aborts, verify mismatch is caught, backup comes first."""
import json

import pytest

from content_engine.publisher import SafePublisher
from content_engine.wordpress import MockWordPress, WordPressClient, WordPressError

POST = {"id": 501, "slug": "demo-post", "title": "Demo Close Checklist", "date": "2025-01-01T08:00:00",  # synthetic
        "content": "<p>Original.</p>"}


@pytest.fixture
def wp():
    return MockWordPress([POST])


def make(wp, tmp_path, dry_run):
    return SafePublisher(wp, tmp_path / "backups", tmp_path / "log.json", dry_run=dry_run)


def run(pub, wp, new="<p>Upgraded.</p>"):
    snapshot = wp.get_post(501)
    return pub.publish(post_id=501, slug="demo-post", snapshot=snapshot, new_content=new)


def test_dry_run_sends_no_write(wp, tmp_path):
    res = run(make(wp, tmp_path, dry_run=True), wp)
    assert res.status == "DRY_RUN"
    assert wp.writes == []
    assert wp.get_post(501)["content"]["raw"] == "<p>Original.</p>"


def test_publish_writes_content_only_and_verifies(wp, tmp_path):
    res = run(make(wp, tmp_path, dry_run=False), wp)
    assert res.status == "OK" and all(res.checks.values())
    assert wp.writes == [(501, {"content": "<p>Upgraded.</p>"})]


def test_drift_aborts_before_write(wp, tmp_path):
    pub = make(wp, tmp_path, dry_run=False)
    snapshot = wp.get_post(501)
    wp.edit_live(501, "<p>Someone fixed a typo.</p>")
    res = pub.publish(post_id=501, slug="demo-post", snapshot=snapshot, new_content="<p>Upgraded.</p>")
    assert res.status == "ABORT_DRIFT" and res.live_changed_since_snapshot is True
    assert wp.writes == []
    assert wp.get_post(501)["content"]["raw"] == "<p>Someone fixed a typo.</p>"


def test_slug_or_status_mismatch_aborts(wp, tmp_path):
    wp.posts[501]["status"] = "draft"
    res = run(make(wp, tmp_path, dry_run=False), wp)
    assert res.status == "ABORT_ASSERT" and wp.writes == []


def test_verify_mismatch_is_reported_with_restore_path(wp, tmp_path):
    wp.tamper = lambda post: post.update(slug="demo-post-2")
    res = run(make(wp, tmp_path, dry_run=False), wp)
    assert res.status == "VERIFY_FAILED"
    assert res.checks["slug"] is False
    assert "restore from" in res.reason and res.backup in res.reason


def test_backup_is_written_before_the_write(wp, tmp_path):
    seen = {}

    def check_backup(post_id):
        files = list((tmp_path / "backups").glob("demo-post.prepublish.*.json"))
        seen["files"] = files
        assert files, "update called before a backup existed"
        assert json.loads(files[0].read_text(encoding="utf-8"))["content"]["raw"] == "<p>Original.</p>"

    wp.before_update = check_backup
    res = run(make(wp, tmp_path, dry_run=False), wp)
    assert res.status == "OK" and seen["files"]


def test_every_outcome_is_logged(wp, tmp_path):
    pub = make(wp, tmp_path, dry_run=True)
    run(pub, wp)
    wp.posts[501]["status"] = "draft"
    run(pub, wp)
    log = json.loads((tmp_path / "log.json").read_text(encoding="utf-8"))
    assert [e["status"] for e in log] == ["DRY_RUN", "ABORT_ASSERT"]
    assert all("at" in e and "backup" in e for e in log)


def test_wordpress_client_refuses_non_content_fields_and_hides_credentials(monkeypatch):
    monkeypatch.setenv("WP_BASE_URL", "https://demo-finance-blog.example.com")
    monkeypatch.setenv("WP_USER", "demo-editor")
    monkeypatch.setenv("WP_APP_PASSWORD", "placeholder-not-real")
    sent = []
    client = WordPressClient.from_env()
    client._open = lambda req, timeout: sent.append(req)
    with pytest.raises(WordPressError):
        client.update_post(501, {"content": "x", "slug": "new"})
    assert sent == []
    assert "placeholder" not in repr(client)


def test_wordpress_client_requires_env(monkeypatch):
    for k in ("WP_BASE_URL", "WP_USER", "WP_APP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(WordPressError):
        WordPressClient.from_env()
