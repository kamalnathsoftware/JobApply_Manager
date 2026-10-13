import pytest

from app.services.llm import LLMError
from app.services.matching import compact_profile, score_job
from tests.helpers import FakeLLM

JOB = {"title": "Python Dev", "company": "Acme", "description": "x" * 20000}
PROFILE = {"skills": ["Python"], "experience": [{"title": "Dev", "company": "A", "junk": 1}]}


def test_score_parsed_and_clamped():
    llm = FakeLLM(
        {
            "score": 87.6,
            "reasoning": "Good fit",
            "matched_skills": ["Python"],
            "missing_skills": ["Go"],
        }
    )
    r = score_job(llm, PROFILE, JOB)
    assert (r.score, r.reasoning, r.matched_skills, r.missing_skills) == (
        88,
        "Good fit",
        ["Python"],
        ["Go"],
    )
    assert score_job(FakeLLM({"score": 250}), PROFILE, JOB).score == 100
    assert score_job(FakeLLM({"score": -5}), PROFILE, JOB).score == 0


def test_job_description_truncated_in_prompt():
    llm = FakeLLM({"score": 50})
    score_job(llm, PROFILE, JOB)
    assert len(llm.calls[0][1]) < 15000


@pytest.mark.parametrize("bad", [{"reasoning": "x"}, {"score": "high"}, ["score"], "text"])
def test_invalid_replies_raise(bad):
    with pytest.raises(LLMError):
        score_job(FakeLLM(bad), PROFILE, JOB)


def test_compact_profile_drops_unknown_fields():
    assert "junk" not in compact_profile(PROFILE)["experience"][0]
