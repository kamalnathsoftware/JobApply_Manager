import pytest

from app.adapters import get_adapter_class
from app.adapters.base import ApplyContext, ApplyStatus, NeedsHuman, SearchCriteria, SiteAdapter
from app.adapters.humanize import Humanizer
from app.adapters.indeed import IndeedAdapter
from app.adapters.indeed import build_search_url as indeed_url
from app.adapters.linkedin import LinkedInAdapter, job_id_from_url
from app.adapters.linkedin import build_search_url as linkedin_url
from app.services.answers import BankEntry, QuestionResolver
from tests.conftest import serve

FAST = Humanizer(sleep=lambda s: None, scale=0)
PROFILE = {
    "contact": {"name": "Asha Rao", "email": "asha@example.com", "phone": "+91 98765 43210"},
    "total_experience_years": 4.0,
}


def ctx(tmp_path, bank=()):
    cv = tmp_path / "cv.pdf"
    cv.write_bytes(b"%PDF-1.4")
    return ApplyContext(PROFILE, str(cv), QuestionResolver(PROFILE, list(bank)), tmp_path / "shots")


def test_registry_has_all_adapters():
    for site in ("naukri", "linkedin", "indeed"):
        cls = get_adapter_class(site)
        assert issubclass(cls, SiteAdapter) and cls.site == site


def test_linkedin_url_builder():
    c = SearchCriteria(
        keywords=["python", "dev"],
        location="Pune",
        posted_within_days=7,
        experience_min=3,
        job_type="contract",
    )
    u = linkedin_url(c)
    assert "keywords=python+dev" in u and "f_AL=true" in u and "f_TPR=r604800" in u
    assert "f_JT=C" in u and "location=Pune" in u and "f_E=3" in u
    assert (
        job_id_from_url("https://www.linkedin.com/jobs/view/python-dev-at-acme-4001/?x=1") == "4001"
    )
    assert job_id_from_url("https://www.linkedin.com/jobs/view/4001/") == "4001"


def test_linkedin_search(page):
    serve(page, {"linkedin.com": "linkedin_search.html"})
    jobs = LinkedInAdapter(page, FAST).search(
        SearchCriteria(keywords=["python"], excluded_companies=["EvilCo"])
    )
    assert [(j.external_id, j.title, j.company) for j in jobs] == [
        ("4001", "Python Developer", "Acme")
    ]
    assert jobs[0].apply_type == "easy" and jobs[0].url.endswith("/jobs/view/4001/")


def test_linkedin_login_wall_and_checkpoint(page):
    ad = LinkedInAdapter(page, FAST)
    serve(page, {"/jobs/search": "<html><body>x</body></html>"})
    page.route(
        "**/checkpoint/**",
        lambda r: r.fulfill(body="<html>verify</html>", content_type="text/html"),
    )
    page.goto("https://www.linkedin.com/checkpoint/challenge/abc")
    with pytest.raises(NeedsHuman) as e:
        ad._guard_auth()
    assert e.value.kind == "captcha"
    page.route("**/login", lambda r: r.fulfill(body="<html>login</html>", content_type="text/html"))
    page.goto("https://www.linkedin.com/login")
    with pytest.raises(NeedsHuman) as e:
        ad._guard_auth()
    assert e.value.kind == "login"


def test_linkedin_easy_apply_end_to_end(page, tmp_path):
    serve(page, {"linkedin.com": "linkedin_job.html"})
    ad = LinkedInAdapter(page, FAST)
    job = ad.get_job("https://www.linkedin.com/jobs/view/4001/")
    assert (
        job.apply_type == "easy"
        and job.title == "Python Developer"
        and "FastAPI" in job.description
    )
    bank = [BankEntry(["python"], "4"), BankEntry(["commuting"], "yes")]
    res = ad.apply(job, ctx(tmp_path, bank))
    assert res.status == ApplyStatus.APPLIED
    sub = page.evaluate("window.__submitted")
    assert sub == {"follow": False, "phone": "+919876543210", "years": "4", "commute": "Yes"}


def test_linkedin_unknown_question_stops_and_discards(page, tmp_path):
    serve(page, {"linkedin.com": "linkedin_job.html"})
    ad = LinkedInAdapter(page, FAST)
    job = ad.get_job("https://www.linkedin.com/jobs/view/4001/")
    with pytest.raises(NeedsHuman) as e:
        ad.apply(job, ctx(tmp_path, bank=[]))
    assert e.value.kind == "unknown_question" and "Python" in e.value.detail
    assert page.evaluate("window.__submitted") is None  # never submitted
    assert page.locator(".jobs-easy-apply-modal").count() == 0  # dialog closed
    assert any((tmp_path / "shots").glob("*question.png"))


def test_linkedin_external_job_is_skipped(page, tmp_path):
    serve(
        page,
        {
            "linkedin.com": "<html><body><h1>T</h1><button class='jobs-apply-button'>Apply</button></body></html>"
        },
    )
    ad = LinkedInAdapter(page, FAST)
    job = ad.get_job("https://www.linkedin.com/jobs/view/4009/")
    assert job.apply_type == "external"
    assert ad.apply(job, ctx(tmp_path)).status == ApplyStatus.SKIPPED


def test_indeed_search_and_url(page, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "indeed_base_url", "https://in.indeed.com/")
    u = indeed_url(SearchCriteria(keywords=["backend"], location="Pune", posted_within_days=3))
    assert (
        u.startswith("https://in.indeed.com/jobs?q=backend") and "fromage=3" in u and "l=Pune" in u
    )
    serve(page, {"indeed.com": "indeed_search.html"})
    jobs = IndeedAdapter(page, FAST).search(
        SearchCriteria(keywords=["backend"], excluded_companies=["bad co"])
    )
    assert [(j.external_id, j.company, j.apply_type) for j in jobs] == [
        ("abc123def456", "Acme", "easy")
    ]
    assert jobs[0].url == "https://in.indeed.com/viewjob?jk=abc123def456"


def test_indeed_apply_end_to_end(page, tmp_path):
    serve(page, {"smartapply.indeed.com": "indeed_apply.html", "indeed.com": "indeed_job.html"})
    ad = IndeedAdapter(page, FAST)
    job = ad.get_job("https://in.indeed.com/viewjob?jk=abc123def456")
    assert job.apply_type == "easy" and job.company == "Acme"
    res = ad.apply(job, ctx(tmp_path, [BankEntry(["driving licence"], "yes")]))
    assert res.status == ApplyStatus.APPLIED
    assert page.evaluate("window.__done") == {"fn": "Asha", "em": "asha@example.com", "dl": "y"}


def test_indeed_unknown_question_needs_human(page, tmp_path):
    serve(page, {"smartapply.indeed.com": "indeed_apply.html", "indeed.com": "indeed_job.html"})
    ad = IndeedAdapter(page, FAST)
    job = ad.get_job("https://in.indeed.com/viewjob?jk=abc123def456")
    with pytest.raises(NeedsHuman) as e:
        ad.apply(job, ctx(tmp_path))
    assert e.value.kind == "unknown_question" and "driving" in e.value.detail.lower()
    assert page.evaluate("window.__done") is None


def test_indeed_captcha_page_stops(page, tmp_path):
    serve(
        page,
        {
            "indeed.com": "<html><body>Additional Verification Required. Verify you are human.</body></html>"
        },
    )
    with pytest.raises(NeedsHuman) as e:
        IndeedAdapter(page, FAST).search(SearchCriteria(keywords=["x"]))
    assert e.value.kind == "captcha"
