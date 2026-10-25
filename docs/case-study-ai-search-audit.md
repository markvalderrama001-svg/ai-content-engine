# Case study: an AI-search audit for a 753-post content site

*Sanitized write-up. The site is Aquarium Store Depot, an affiliate fishkeeping blog I own. Only
aggregate numbers are shown: no page-level data, no internal URLs, no account identifiers.*

## The question

The site lost search traffic in Google's helpful-content era and wanted to know two things: is it
being cited by AI answers (Google AI Overviews / AI Mode, Bing Copilot, ChatGPT), and what should
the upgrade pipeline in this repo work on first?

I treated it like an audit: pull the population from the systems of record, reconcile the sources,
group the population, then test a small sample before scaling.

## Sources and method

| Source | What it gave | Window |
|---|---|---|
| Google Search Console, search results | Clicks, impressions, CTR, position by page | 16 months |
| Google Search Console, Generative AI report | AI impressions by page | since spring 2026 |
| Bing Webmaster Tools, AI Performance | Copilot citations by page and by grounding query | 3 months |
| GA4 | Sessions by channel, including the AI-assistant channel | 3 months |
| Sitemap and WordPress REST API (read-only) | The full post inventory, modified dates, schema present | point in time |
| Live page checks | robots.txt, llms.txt, structured data, page weight | point in time |

Method, in order:
1. **Inventory first.** Catalog every published post (753) so every later number has a denominator.
2. **Join the sources on URL.** One row per page: clicks, impressions, AI impressions, Bing citations.
3. **Group by content type** using the URL pattern (tank-mates pages, questions / how-to, product
   roundups, "types of" lists, species care guides).
4. **Concentration analysis.** How much of the AI visibility sits in the top 10 and top 100 pages.
5. **Technical sample.** Crawl rules, schema and modified dates on a sample of pages.
6. **Check guidance before acting.** Each planned change was checked against current public guidance
   from Google and Microsoft and published studies. Several planned items were dropped as a result.

## Headline numbers

| Measure | Value |
|---|---|
| Posts cataloged | 753 |
| Google Search, 16 months | 488K clicks, 57.4M impressions (0.8% CTR, average position 10.3) |
| Google AI impressions | 247K across 1,000 URLs |
| Bing / Copilot citations, 3 months | 780.8K across 545 pages |
| Species care guides already rebuilt | about 215, across 7 of 20 planned pillars |

## Findings (generalized)

1. **AI cites overview and decision pages, not single-topic reference pages.** Google's AI surfaces
   favored "what goes with what" pages, direct questions and product picks. Bing favored broad
   "types of X" overviews. The deep single-species guides, where most of the writing effort had gone,
   were cited far less.
2. **Visibility is concentrated.** The top 10 pages held about a fifth of Google AI impressions and
   the top 100 about two thirds. On Bing, a single overview page carried roughly a quarter of all
   citations: the most valuable asset and a single point of failure.
3. **AI visibility is not traffic.** Close to a million combined AI impressions and citations
   produced only a small number of tracked sessions. The payoff is brand presence in answers and the
   ranking strength that comes with being a trusted source, not clicks from AI.
4. **Overlapping pages compete.** Hub pages and older "types of" pages covered the same head terms.
5. **The technical base was sound, with two real problems.** No AI crawlers were blocked and
   Article / Person / Breadcrumb / Video schema was present. But FAQ markup was inconsistent, and a
   bulk update had stamped the same "modified" date on most posts, flattening the freshness signal.

## Action plan (P1 to P8)

| Priority | Workstream | What it means in practice |
|---|---|---|
| P1 | Protect and upgrade the pages AI already cites | Run the ~25 most-cited pages through the full pipeline as content-only updates. Change the most valuable page last and most conservatively. |
| P2 | Make hub pages the citable overview for their head term | A short definition, a comparison table and the author's own ranking, after resolving overlap with older list pages. |
| P3 | Upgrade the decision-page cluster | The page type AI cites most, with a stricter humanizer bar and the author's confirmed list of species kept. |
| P4 | Template changes for new and upgraded guides | A direct answer where it reads naturally, a visible FAQ, a quick-facts block. No mass rewrite. |
| P5 | Technical cleanup | Fix the bulk modified-date problem first, then investigate index exclusions, crawler responses in logs, IndexNow. |
| P6 | Measurement | A monthly snapshot of AI impressions, citations by page and query, and AI-assistant sessions. |
| P7 | Brand and video | Use the existing video library: descriptions linking to matching articles, consistent brand naming. Brand mentions correlate with AI visibility more than links do. |
| P8 | Ads and page weight | Review ad density and HTML weight on pages hit by the late-2025 core update. |

### What the research check changed

- **FAQ schema** was demoted from a goal to "leave existing markup alone": FAQ rich results were
  retired and a large public test found no citation gain from adding it. Visible FAQ sections stay.
  (The injector in this repo is still useful for keeping markup consistent with visible content.)
- **llms.txt and AI-specific chunking** were dropped as unnecessary.
- **Modified dates** moved to the top of the cleanup list: an inaccurate lastmod is worse than none.
- **AI-assisted content** is allowed by policy; unreviewed scaled content is the risk. That is the
  argument for the gates in this repo and for a human read before publishing.

## Execution and safeguards

The plan ran through the pipeline this repo reimplements:
- **Pilot:** 10 live pages upgraded and published as content-only updates. All 10 passed post-update
  verification (title, slug and publish date unchanged) with no drift since backup.
- **Batch:** 20 pages with per-page scores (review, voice, information gain), a list of every advice
  change, every removed first-person claim and every open question for the author.

Safeguards that held regardless of pace: the live original saved right before every write, URL and
title unchanged on cited pages, modified date changed only with real edits, automated checks on every
page (em dashes, banned phrasing, unconfirmed first-person claims, competitor mentions), and both
score gates on every page.
