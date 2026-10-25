# ai-content-engine: orchestration guide for Claude Code

This repo ships the editorial pipeline twice: as Python (`content_engine/`, runs unattended) and as
Claude Code subagents (`.claude/agents/`, runs inside a session). Both follow the same gates.

## Running the team in a session
Keep each article's files in `work/<slug>/`.

1. Fetch the live post read-only and save `original.html`. Save the author's confirmed notes as `notes.json`.
   Never edit the live site at this step.
2. **writer** then **reviewer**. If `review.json` scores below 9, copy `required_fixes` into `brief.md`
   and run the writer again. Maximum 3 rounds, then stop and report BLOCKED with the last review.
3. **polisher** once. Re-run the mechanical checks; if one fails, restore the pre-polish draft.
4. **humanizer**. Accept `humanized.html` only if `voice_score` is 9 or more and the mechanical checks
   pass. Maximum 2 attempts.
5. **info-gain-judge**. Sum the dimensions yourself. Below 7/8, send `missing` to the writer once,
   have the reviewer re-verify (still 9 or more), then judge again. Maximum 2 judge rounds.
6. The final draft must pass the mechanical checks. Then stop: a human reads it.

Mechanical checks from a session:
`python -c "import sys; from content_engine.mechanical import check_article; from content_engine.config import EditorialRules; print(check_article(open(sys.argv[1], encoding='utf-8').read(), EditorialRules()).summary())" work/<slug>/draft.html`

## Rules that do not bend
- Agents never publish. Publishing is `python -m content_engine --slugs ... --publish`, run by a
  human after reading the draft ("Claude drafts, a human posts").
- Never write first-person experience the notes do not confirm.
- Never skip a gate because a score is close. 8 is not 9.
- Credentials come from environment variables only. Never print them or write them to a file.

## Code map
- `content_engine/orchestrator.py`: gates and bounded loops.
- `content_engine/mechanical.py`: em dashes, banned phrases, competitors, first-person claims, preservation.
- `content_engine/publisher.py`: backup, assert, drift check, update, verify, log.
- Tests: `.venv/Scripts/python -m pytest -q` (offline).
