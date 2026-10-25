"""Command line entry point.

  python -m content_engine --demo                      offline demo (mock WordPress, fake LLM)
  python -m content_engine --slugs a b --notes n.json  real run: dry-run by default
  python -m content_engine --slugs a b --notes n.json --publish [--submit]
  python -m content_engine --show-log output/demo/publish_log.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

from .config import Settings
from .indexnow import IndexNowSubmitter
from .llm import get_llm
from .orchestrator import Article, run_article
from .publisher import SafePublisher
from .reports import Console, log_table, review_report_md
from .wordpress import MockWordPress, WordPressClient

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
DEMO_MARKER = ".content-engine-demo"


def _header(con: Console, settings: Settings, llm_name: str, target: str) -> None:
    g = settings.gates
    con.line(con.c("ai-content-engine", "bold") + f"  | target: {target} | LLM: {llm_name}")
    con.line(con.c(f"gates: review >={g.review_min}/10 (max {g.max_review_rounds} rounds), "
                   f"voice >={g.voice_min}/10, info-gain >={g.info_gain_min}/8 | "
                   f"publish: backup -> assert -> drift check -> update -> verify -> log", "grey"))


def _process(con, settings, llm, client, publisher, articles, out: Path, before_publish=None):
    out.joinpath("reports").mkdir(parents=True, exist_ok=True)
    out.joinpath("originals").mkdir(parents=True, exist_ok=True)
    published_urls = []
    for n, (post_id, article) in enumerate(articles, 1):
        con.line("")
        con.line(con.c(f"[{n}/{len(articles)}] {article.slug}", "cyan") + f"  {article.title}")
        snapshot = client.get_post(post_id)  # the version the pipeline works from
        out.joinpath("originals", f"{article.slug}.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
        article.html = snapshot["content"]["raw"]
        res = run_article(article, llm, settings, emit=con.event)
        pub = None
        if res.ready:
            out.joinpath("drafts").mkdir(exist_ok=True)
            out.joinpath("drafts", f"{article.slug}.html").write_text(res.final_html, encoding="utf-8")
            if before_publish:
                before_publish(post_id, article.slug)
            pub = publisher.publish(post_id=post_id, slug=article.slug, snapshot=snapshot,
                                    new_content=res.final_html, scores=res.scores)
            con.publish(pub)
            if pub.status == "OK":
                published_urls.append(pub.link)
        out.joinpath("reports", f"{article.slug}.md").write_text(review_report_md(res, pub), encoding="utf-8")
    return published_urls


def _finish(con, out: Path, submitter: IndexNowSubmitter, urls: list[str]) -> None:
    con.line("")
    con.line(con.c("publish log", "bold") + f"  ({(out / 'publish_log.json').as_posix()})")
    log = json.loads((out / "publish_log.json").read_text(encoding="utf-8")) if (out / "publish_log.json").exists() else []
    log_table(log, con)
    con.line("")
    for b in submitter.submit(urls) if urls else []:
        color = {"OK": "green", "DRY_RUN": "yellow"}.get(b.status, "red")
        con.line(con.c("indexnow", "bold") + f"  {con.c(b.status, color)}  {b.detail}")
        for u in b.urls:
            con.line(con.c(f"          {u}", "grey"))
    con.line(con.c(f"\nreview reports: {(out / 'reports').as_posix()}/", "grey"))


def run_demo(args, con: Console) -> int:
    settings = Settings.from_env()
    llm = get_llm(force_fake=not args.live_llm)
    site = json.loads((FIXTURES / "demo_site.json").read_text(encoding="utf-8"))
    notes = json.loads((FIXTURES / "author_notes.json").read_text(encoding="utf-8"))
    out = Path(args.out or "output/demo")
    if out.exists() and (out / DEMO_MARKER).exists():
        shutil.rmtree(out)  # only ever removes a folder this demo created
    out.mkdir(parents=True, exist_ok=True)
    (out / DEMO_MARKER).write_text("created by content_engine --demo\n", encoding="utf-8")

    posts = []
    for p in site["posts"]:
        posts.append({**p, "content": (FIXTURES / p["file"]).read_text(encoding="utf-8")})
    wp = MockWordPress(posts, site=site["site"])
    host = urlparse(site["site"]).hostname
    _header(con, settings, llm.name, f"{host} (in-memory mock WordPress)")

    def simulate_edit(post_id: int, slug: str) -> None:
        extra = site.get("simulate_live_edit", {}).get(slug)
        if extra:
            con.line(con.c("  [simulated]    an editor changes the live post in wp-admin before the write", "yellow"))
            wp.edit_live(post_id, wp.get_post(post_id)["content"]["raw"] + "\n" + extra)

    publisher = SafePublisher(wp, out / "backups", out / "publish_log.json", dry_run=args.dry_run,
                              mode_label="dry-run" if args.dry_run else "mock-publish")
    articles = [(p["id"], Article(p["slug"], p["title"], "", notes.get(p["slug"], {}))) for p in site["posts"]]
    urls = _process(con, settings, llm, wp, publisher, articles, out, before_publish=simulate_edit)
    _finish(con, out, IndexNowSubmitter(host, dry_run=True), urls)
    return 0


def run_live(args, con: Console) -> int:
    settings = Settings.from_env()
    llm = get_llm()
    client = WordPressClient.from_env()
    notes = json.loads(Path(args.notes).read_text(encoding="utf-8")) if args.notes else {}
    out = Path(args.out or "output/run")
    host = urlparse(client.base).hostname
    _header(con, settings, llm.name, f"{host} ({'PUBLISH' if args.publish else 'dry-run'})")
    articles = []
    for slug in args.slugs:
        post = client.find_post_by_slug(slug)
        if not post:
            con.line(con.c(f"skip {slug}: no published post with that slug", "red"))
            continue
        articles.append((post["id"], Article(slug, post["title"]["raw"], "", notes.get(slug, {}))))
    publisher = SafePublisher(client, out / "backups", out / "publish_log.json", dry_run=not args.publish)
    urls = _process(con, settings, llm, client, publisher, articles, out)
    _finish(con, out, IndexNowSubmitter.from_env(host, dry_run=not args.submit), urls)
    return 0


def load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader: KEY=VALUE lines, never overrides variables already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv()
    ap = argparse.ArgumentParser(prog="content_engine", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--demo", action="store_true", help="offline demo on synthetic fixtures")
    ap.add_argument("--live-llm", action="store_true", help="demo: use the Anthropic API instead of the fake LLM")
    ap.add_argument("--dry-run", action="store_true", help="demo: stop before the write even on the mock")
    ap.add_argument("--slugs", nargs="+", help="real run: slugs of live posts to upgrade")
    ap.add_argument("--notes", help="real run: JSON of author notes keyed by slug")
    ap.add_argument("--publish", action="store_true", help="real run: actually write to WordPress")
    ap.add_argument("--submit", action="store_true", help="real run: actually submit URLs to IndexNow")
    ap.add_argument("--out", help="output folder (default output/demo or output/run)")
    ap.add_argument("--show-log", metavar="PATH", help="print a publish log as a table")
    ap.add_argument("--color", action="store_true", default=None, help="force ANSI colors")
    args = ap.parse_args(argv)
    con = Console(color=args.color)

    if args.show_log:
        log_table(json.loads(Path(args.show_log).read_text(encoding="utf-8")), con)
        return 0
    if args.demo:
        return run_demo(args, con)
    if args.slugs:
        return run_live(args, con)
    ap.print_help()
    return 2
