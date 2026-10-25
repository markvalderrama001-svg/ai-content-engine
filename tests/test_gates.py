"""Score gates and bounded retry loops."""
import json

from conftest import ScriptedLLM

from content_engine.config import Gates, Settings
from content_engine.fake_llm import FakeLLM
from content_engine.orchestrator import run_article


def review(score):
    return json.dumps({"score": score, "required_fixes": ["Add memorable line: something sharper"]})


def test_failed_review_goes_back_to_writer_then_passes(card):
    llm = FakeLLM()
    res = run_article(card, llm, Settings())
    reviews = [e for e in res.events if e.stage == "reviewer"]
    assert [e.score for e in reviews] == [7, 9]
    assert reviews[0].passed is False and reviews[1].passed is True
    assert llm.calls[:4] == ["writer", "reviewer", "writer", "reviewer"]
    assert res.status == "READY"


def test_score_of_8_never_passes_a_gate_of_9(card):
    llm = ScriptedLLM(reviewer=review(8))
    res = run_article(card, llm, Settings())
    assert res.status == "BLOCKED" and res.blocked_at == "review gate"


def test_review_loop_is_bounded(card):
    llm = ScriptedLLM(reviewer=review(5))
    res = run_article(card, llm, Settings(gates=Gates(max_review_rounds=3)))
    assert llm.calls.count("writer") == 3
    assert llm.calls.count("reviewer") == 3
    assert "polisher" not in llm.calls  # nothing downstream runs after a block
    assert res.status == "BLOCKED"


def test_judge_score_is_clamped_not_trusted(card):
    llm = ScriptedLLM(reviewer=json.dumps({"score": 99}), info_gain_judge=json.dumps(
        {"dimensions": {"proprietary_data": 50, "first_hand": 0, "original_framework": 0,
                        "expert_attribution": 0, "freshness": 0}}))
    res = run_article(card, llm, Settings())
    assert res.reviews[0]["score"] == 10
    assert res.info_gain["total"] == 2  # 50 clamped to the dimension max of 2
    assert res.status == "BLOCKED" and res.blocked_at == "info-gain gate"


def test_unparseable_review_counts_as_a_failed_round(card):
    llm = ScriptedLLM(reviewer="Looks great to me!")
    res = run_article(card, llm, Settings())
    assert res.status == "BLOCKED"
    assert all(r["score"] == 0 for r in res.reviews)


def test_humanizer_self_score_is_overridden_when_code_finds_tells(card):
    def dashed(payload):
        return json.dumps({"voice_score": 10, "html": payload["article_html"].replace(
            "</p>", " — truly.</p>", 1), "notes": []})

    llm = ScriptedLLM(humanizer=dashed)
    res = run_article(card, llm, Settings(gates=Gates(max_voice_rounds=2)))
    voice = [e for e in res.events if e.stage == "humanizer"]
    assert [e.score for e in voice] == [6, 6]
    assert llm.calls.count("humanizer") == 2
    assert res.status == "BLOCKED" and res.blocked_at == "voice gate"


def test_info_gain_failure_sends_brief_back_and_reverifies(accrual):
    accrual.notes = {**accrual.notes, "freshness": "Updated October 2026: method guidance re-checked."}
    judged, briefs = [], []
    low = {"dimensions": {"proprietary_data": 2, "first_hand": 2, "original_framework": 2,
                          "expert_attribution": 0, "freshness": 0},
           "missing": ["freshness: add a dated update note", "expert_attribution: add an Expert Take"]}

    def judge(payload):
        judged.append(payload["article_html"])
        if len(judged) == 1:
            return json.dumps(low)
        return FakeLLM().complete(stage="info-gain-judge", system="", user=json.dumps(payload), model="m")

    def writer(payload):
        briefs.append(payload["brief"])
        return FakeLLM().complete(stage="writer", system="", user=json.dumps(payload), model="m")

    llm = ScriptedLLM(info_gain_judge=judge, writer=writer)
    res = run_article(accrual, llm, Settings())
    assert [e.score for e in res.events if e.stage == "info-gain"] == [6, 8]
    assert any("freshness" in " ".join(b) for b in briefs[1:])
    assert "re-verify after info-gain fix" in [e.detail for e in res.events]
    assert 'class="freshness"' in res.final_html
    assert res.status == "READY"


def test_info_gain_gate_blocks_after_bounded_rounds(accrual):
    llm = FakeLLM()
    res = run_article(accrual, llm, Settings(gates=Gates(info_gain_min=8, max_info_gain_rounds=2)))
    assert [e.score for e in res.events if e.stage == "info-gain"] == [7, 7]
    assert llm.calls.count("info-gain-judge") == 2
    assert res.status == "BLOCKED" and res.blocked_at == "info-gain gate"
    assert "freshness" in res.reason


def test_polisher_that_breaks_a_check_is_rolled_back(close):
    llm = ScriptedLLM(polisher=lambda p: p["article_html"].replace("Process Overview", "Overview"))
    res = run_article(close, llm, Settings())
    pol = next(e for e in res.events if e.stage == "polisher")
    assert pol.passed is False and "rolled back" in pol.detail
    assert "Process Overview" in res.final_html
    assert res.status == "READY"


def test_all_three_demo_articles_reach_ready(card, close, accrual):
    for art in (card, close, accrual):
        assert run_article(art, FakeLLM(), Settings()).status == "READY"
