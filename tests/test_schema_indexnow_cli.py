import json

from content_engine.cli import main
from content_engine.faq_schema import extract_faq_pairs, inject_faq_schema
from content_engine.indexnow import IndexNowSubmitter

FAQ = ('<h2 id="faq">FAQ</h2><h3>Q one?</h3><p>Answer one.</p><h3>Q two?</h3><p>Answer</p><p>two.</p>'
       '<h2>Closing</h2><h3>Not a question</h3><p>Outside the FAQ.</p>')


def test_extracts_only_visible_faq_pairs():
    assert extract_faq_pairs(FAQ) == [("Q one?", "Answer one."), ("Q two?", "Answer two.")]


def test_injection_is_valid_and_idempotent():
    first = inject_faq_schema(FAQ)
    assert first.injected and len(first.pairs) == 2
    block = first.html[first.html.index("<script"):]
    data = json.loads(block[block.index(">") + 1: block.rindex("</script>")])
    assert data["@type"] == "FAQPage" and len(data["mainEntity"]) == 2
    second = inject_faq_schema(first.html)
    assert not second.injected and second.html == first.html


def test_no_faq_section_means_no_schema():
    res = inject_faq_schema("<h2>Setup</h2><h3>Accounts</h3><p>Ten accounts.</p>")
    assert not res.injected and "script" not in res.html


def test_indexnow_dry_run_and_host_allowlist():
    sent = []
    sub = IndexNowSubmitter("demo-finance-blog.example.com", "demo-key", transport=lambda r: sent.append(r) or 200)
    res = sub.submit(["https://demo-finance-blog.example.com/a/", "https://elsewhere.example.org/b/"])
    assert [r.status for r in res] == ["REJECTED", "DRY_RUN"]
    assert sent == []


def test_indexnow_live_batches_and_bounded_retries():
    codes = iter([500, 500, 500, 200])
    sent, slept = [], []

    def transport(req):
        sent.append(json.loads(req.data))
        return next(codes)

    sub = IndexNowSubmitter("demo-finance-blog.example.com", "demo-key", dry_run=False, batch_size=2, max_retries=3,
                            transport=transport, sleep=slept.append)
    urls = [f"https://demo-finance-blog.example.com/p{i}/" for i in range(3)]
    res = sub.submit(urls)
    assert [r.status for r in res] == ["FAILED", "OK"]
    assert len(sent) == 4 and slept == [1, 2, 4]
    assert sent[-1]["urlList"] == ["https://demo-finance-blog.example.com/p2/"]


def test_indexnow_403_is_not_retried():
    calls = []
    sub = IndexNowSubmitter("demo-finance-blog.example.com", "k", dry_run=False,
                            transport=lambda r: calls.append(1) or 403, sleep=lambda s: None)
    assert sub.submit(["https://demo-finance-blog.example.com/a/"])[0].status == "FAILED"
    assert len(calls) == 1


def test_demo_end_to_end(tmp_path, capsys):
    out = tmp_path / "demo"
    assert main(["--demo", "--out", str(out)]) == 0
    log = json.loads((out / "publish_log.json").read_text(encoding="utf-8"))
    assert [(e["slug"], e["status"]) for e in log] == [
        ("card-reconciliation", "OK"), ("month-end-close", "ABORT_DRIFT"), ("cash-vs-accrual", "OK")]
    assert len(list((out / "backups").glob("*.json"))) == 3
    assert (out / "reports" / "card-reconciliation.md").read_text(encoding="utf-8").count("## Reviewer round") == 2
    text = capsys.readouterr().out
    assert "FAIL >=9" in text and "ABORT_DRIFT" in text and "DRY_RUN" in text


def test_demo_dry_run_writes_nothing(tmp_path):
    out = tmp_path / "demo"
    assert main(["--demo", "--dry-run", "--out", str(out)]) == 0
    log = json.loads((out / "publish_log.json").read_text(encoding="utf-8"))
    assert [e["status"] for e in log] == ["DRY_RUN", "ABORT_DRIFT", "DRY_RUN"]
