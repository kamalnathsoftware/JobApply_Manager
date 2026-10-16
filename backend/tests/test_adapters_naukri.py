import pytest

from app.adapters import get_adapter_class
from app.adapters.base import (
    ApplyContext,
    ApplyStatus,
    NeedsHuman,
    SearchCriteria,
    SiteAdapter,
)
from app.adapters.humanize import Humanizer
from app.adapters.naukri import NaukriAdapter, build_search_url, job_id_from_url
from app.services.answers import BankEntry, QuestionResolver
from tests.conftest import serve

FAST = Humanizer(sleep=lambda s: None, scale=0)


def ctx(tmp_path, bank=None):
    return ApplyContext(
        profile={"contact": {"email": "a@b.co"}, "total_experience_years": 4},
        resume_path=str(tmp_path / "cv.pdf"),
        resolver=QuestionResolver(profile={"total_experience_years": 4}, bank=bank or []),
        screenshot_dir=tmp_path / "shots",
    )


def test_interface_and_registry():
    cls = get_adapter_class("naukri")
    assert cls is NaukriAdapter and issubclass(cls, SiteAdapter)
    for m in ("search", "get_job", "apply"):
        assert callable(getattr(cls, m))
    with pytest.raises(ValueError):
        get_adapter_class("nope")


def test_build_search_url_and_ids():
    c = SearchCriteria(
        keywords=["python", "fastapi"], location="Bengaluru", experience_min=3, posted_within_days=7
    )
    url = build_search_url(c)
    assert url.startswith("https://www.naukri.com/python-fastapi-jobs-in-bengaluru?")
    assert "k=python%2C+fastapi" in url and "experience=3" in url and "jobAge=7" in url
    assert "-jobs-in-bengaluru-2?" in build_search_url(c, 2)
    assert (
        job_id_from_url("https://www.naukri.com/job-listings-x-y-123456789012?src=a")
        == "123456789012"
    )


def test_search_parses_cards_and_excludes_companies(page):
    serve(page, {"naukri.com": "naukri_search.html"})
    jobs = NaukriAdapter(page, FAST).search(
        SearchCriteria(keywords=["python"], excluded_companies=["evilco"], max_results=10)
    )
    assert [j.title for j in jobs] == ["Python Developer", "SDE II"]
    first = jobs[0]
    assert first.external_id == "111111111111" and first.company == "Acme Corp"
    assert "3-5" in first.experience and "Lacs" in first.salary and first.location == "Bengaluru"
    assert jobs[1].external_id == "333333333333"  # id derived from URL when attribute missing


def test_search_respects_max_results(page):
    serve(page, {"naukri.com": "naukri_search.html"})
    jobs = NaukriAdapter(page, FAST).search(SearchCriteria(keywords=["python"], max_results=1))
    assert len(jobs) == 1


def test_search_stops_on_captcha(page):
    serve(page, {"naukri.com": "<html><body>Please verify you are human to continue</body></html>"})
    with pytest.raises(NeedsHuman) as e:
        NaukriAdapter(page, FAST).search(SearchCriteria(keywords=["python"]))
    assert e.value.kind == "captcha"


def test_get_job(page):
    serve(page, {"naukri.com": "naukri_job.html"})
    job = NaukriAdapter(page, FAST).get_job("https://www.naukri.com/job-listings-x-111111111111")
    assert job.title == "Python Developer" and job.company == "Acme Corp"
    assert "FastAPI" in job.description and job.apply_type == "easy" and not job.already_applied


def test_apply_answers_screening_questions_from_bank(page, tmp_path):
    serve(page, {"naukri.com": "naukri_job.html"})
    ad = NaukriAdapter(page, FAST)
    job = ad.get_job("https://www.naukri.com/job-listings-x-111111111111")
    bank = [BankEntry(["expected ctc"], "18 LPA"), BankEntry(["relocate"], "yes")]
    res = ad.apply(job, ctx(tmp_path, bank))
    assert res.status == ApplyStatus.APPLIED
    assert page.evaluate("window.__answers") == ["18 LPA", "Yes"]
    assert res.screenshot_path and (tmp_path / "shots").exists()


def test_apply_unknown_question_needs_human(page, tmp_path):
    serve(page, {"naukri.com": "naukri_job.html"})
    ad = NaukriAdapter(page, FAST)
    job = ad.get_job("https://www.naukri.com/job-listings-x-111111111111")
    with pytest.raises(NeedsHuman) as e:
        ad.apply(job, ctx(tmp_path, bank=[]))
    assert e.value.kind == "unknown_question" and "expected CTC" in e.value.detail
    assert any((tmp_path / "shots").glob("*question.png"))


def test_apply_already_applied_and_external(page, tmp_path):
    serve(
        page,
        {
            "naukri.com": "<html><body><h1>T</h1><button id='already-applied'>Already Applied</button></body></html>"
        },
    )
    ad = NaukriAdapter(page, FAST)
    job = ad.get_job("https://www.naukri.com/job-listings-x-111111111111")
    assert job.already_applied
    assert ad.apply(job, ctx(tmp_path)).status == ApplyStatus.ALREADY_APPLIED
    serve_ext = "<html><body><h1>T</h1><button id='company-site-button' onclick=\"window.open('https://careers.initech.test/x')\">Apply on company site</button></body></html>"
    page.unroute_all()
    serve(page, {"naukri.com": serve_ext})
    job = ad.get_job("https://www.naukri.com/job-listings-x-111111111111")
    assert job.apply_type == "external"
    # the redirect target has no form -> stops for a person, tagged so the Naukri account keeps going
    with pytest.raises(NeedsHuman) as e:
        ad.apply(job, ctx(tmp_path))
    assert e.value.kind.startswith("external_")


COMPANY_CTX = {
    "profile": {
        "contact": {"name": "Asha Rao", "email": "asha@example.com", "phone": "+91 98765 43210"},
        "education": [{"institution": "NIT", "degree": "B.Tech"}],
        "total_experience_years": 5.0,
    }
}


def _external_ctx(tmp_path):
    cv = tmp_path / "Asha_Rao_CV.pdf"
    cv.write_bytes(b"%PDF-1.4")
    prof = COMPANY_CTX["profile"]
    return ApplyContext(
        prof,
        str(cv),
        QuestionResolver(prof, [BankEntry(["expected salary"], "20 LPA")]),
        tmp_path / "shots",
    )


@pytest.mark.parametrize(
    "button",
    [
        "<button id='company-site-button' onclick=\"window.open('https://careers.initech.test/jobs/1')\">Apply on company site</button>",
        "<a id='company-site-button' href='https://careers.initech.test/jobs/1'>Apply on company site</a>",
        "<a id='company-site-button' target='_blank' href='https://careers.initech.test/jobs/1'>Apply on company site</a>",
    ],
)
def test_external_redirect_applies_on_company_site(page, tmp_path, button):
    from tests.test_company_site import edu_llm

    serve(
        page,
        {
            "naukri.com": f"<html><body><h1>T</h1>{button}</body></html>",
            "initech.test": "company_careers.html",
        },
    )
    ad = NaukriAdapter(page, FAST)
    job = ad.get_job("https://www.naukri.com/job-listings-x-111111111111")
    assert job.apply_type == "external"
    c = _external_ctx(tmp_path)
    c.llm = edu_llm()
    res = ad.apply(job, c)
    assert res.status == ApplyStatus.APPLIED and "company site" in res.message
    assert ad.page is page and len(page.context.pages) == 1  # extra tab closed, board page restored
