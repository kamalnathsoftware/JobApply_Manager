import pytest

from app.adapters import get_adapter_class
from app.adapters.base import ApplyContext, ApplyStatus, NeedsHuman, SearchCriteria
from app.adapters.company_site import CompanySiteAdapter
from app.adapters.forms import Field
from app.adapters.humanize import Humanizer
from app.services.answers import BankEntry, QuestionResolver
from app.services.field_mapper import map_fields
from app.services.llm import LLMError
from tests.conftest import serve
from tests.helpers import FakeLLM

FAST = Humanizer(sleep=lambda s: None, scale=0)
PROFILE = {
    "contact": {"name": "Asha Rao", "email": "asha@example.com", "phone": "+91 98765 43210"},
    "education": [{"institution": "NIT", "degree": "B.Tech"}],
    "total_experience_years": 5.0,
}
URL = "https://careers.initech.test/jobs/1"


def ctx(tmp_path, llm=None, bank=(("expected salary", "20 LPA"),)):
    cv = tmp_path / "Asha_Rao_CV.pdf"
    cv.write_bytes(b"%PDF-1.4")
    entries = [BankEntry([p], a) for p, a in bank]
    return ApplyContext(
        PROFILE, str(cv), QuestionResolver(PROFILE, entries), tmp_path / "shots", llm=llm
    )


def edu_llm(value="Bachelor's degree"):
    """Maps the qualification select only; everything else null."""

    def fn(system, user):
        import json

        fields = json.loads(user)["fields"]
        return {
            "values": {
                f["id"]: (value if "qualification" in f["label"].lower() else None) for f in fields
            }
        }

    return FakeLLM(fn)


def test_registry_and_search_returns_supplied_urls():
    assert get_adapter_class("company") is CompanySiteAdapter
    jobs = CompanySiteAdapter(None, FAST).search(
        SearchCriteria(keywords=["x"], company_urls=[URL, "https://b.test/apply"], max_results=5)
    )
    assert [j.url for j in jobs] == [URL, "https://b.test/apply"]
    assert (
        len({j.external_id for j in jobs}) == 2
        and jobs[0].external_id
        == CompanySiteAdapter(None)
        .search(SearchCriteria(keywords=["x"], company_urls=[URL]))[0]
        .external_id
    )  # stable ids


def test_get_job_reads_title_and_text(page):
    serve(page, {"initech.test": "company_careers.html"})
    job = CompanySiteAdapter(page, FAST).get_job(URL)
    assert job.title == "Senior Python Engineer" and "Initech is hiring" in job.description


def test_apply_fills_from_resume_and_claude_mapping(page, tmp_path):
    serve(page, {"initech.test": "company_careers.html"})
    ad = CompanySiteAdapter(page, FAST)
    res = ad.apply(ad.get_job(URL), ctx(tmp_path, llm=edu_llm()))
    assert res.status == ApplyStatus.APPLIED and res.screenshot_path
    # the page replaced itself after submit; read what was sent via the success page state
    assert "Thank you for applying" in page.inner_text("body")


def test_submitted_values_are_correct(page, tmp_path):
    html = (tmp_path.parent / "x").name  # noqa: F841
    from tests.conftest import FIXTURES

    src = (
        (FIXTURES / "company_careers.html")
        .read_text()
        .replace(
            "document.body.innerHTML = '<h1>Thank you",
            "document.title = JSON.stringify(window.__sent); document.body.innerHTML = '<h1>Thank you",
        )
    )
    serve(page, {"initech.test": src})
    ad = CompanySiteAdapter(page, FAST)
    ad.apply(ad.get_job(URL), ctx(tmp_path, llm=edu_llm()))
    import json

    sent = json.loads(page.title())
    assert sent == {
        "fn": "Asha",
        "ln": "Rao",
        "em": "asha@example.com",
        "ph": "+919876543210",
        "edu": "Bachelor's degree",
        "sal": "20 LPA",
        "file": "Asha_Rao_CV.pdf",
    }


def test_unknown_required_select_without_llm_needs_human(page, tmp_path):
    serve(page, {"initech.test": "company_careers.html"})
    ad = CompanySiteAdapter(page, FAST)
    with pytest.raises(NeedsHuman) as e:
        ad.apply(ad.get_job(URL), ctx(tmp_path, llm=None))
    assert e.value.kind == "unknown_question" and "qualification" in e.value.detail.lower()
    assert any((tmp_path / "shots").glob("*unknown_field.png"))


def test_claude_returning_null_or_bad_option_does_not_guess(page, tmp_path):
    serve(page, {"initech.test": "company_careers.html"})
    ad = CompanySiteAdapter(page, FAST)
    with pytest.raises(NeedsHuman):
        ad.apply(
            ad.get_job(URL), ctx(tmp_path, llm=edu_llm("PhD in Astrophysics"))
        )  # not an option
    page.reload()


def test_essay_question_stops_even_with_claude(page, tmp_path):
    serve(page, {"initech.test": "company_careers_essay.html"})
    ad = CompanySiteAdapter(page, FAST)
    llm = FakeLLM(lambda s, u: {"values": {}})
    with pytest.raises(NeedsHuman) as e:
        ad.apply(ad.get_job(URL), ctx(tmp_path, llm=llm))
    assert "Why do you want" in e.value.detail
    assert page.evaluate("window.__sent") is None


def test_consent_checkbox_is_never_ticked_for_the_user(page, tmp_path):
    serve(page, {"initech.test": "company_careers_consent.html"})
    ad = CompanySiteAdapter(page, FAST)
    with pytest.raises(NeedsHuman) as e:
        ad.apply(ad.get_job(URL), ctx(tmp_path, llm=edu_llm()))
    assert "privacy" in e.value.detail.lower()
    assert not page.is_checked("#consent")


def test_login_and_account_creation_walls(page, tmp_path):
    ad = CompanySiteAdapter(page, FAST)
    serve(page, {"initech.test": "company_login.html"})
    with pytest.raises(NeedsHuman) as e:
        ad.apply(ad.get_job(URL), ctx(tmp_path))
    assert e.value.kind == "login"
    page.unroute_all()
    serve(page, {"initech.test": "company_signup.html"})
    with pytest.raises(NeedsHuman) as e:
        ad.apply(ad.get_job(URL), ctx(tmp_path))
    assert e.value.kind == "account_required"
    assert page.locator("input[type=password]").first.input_value() == ""  # nothing typed


def test_captcha_page_stops(page, tmp_path):
    serve(
        page,
        {
            "initech.test": "<html><body><h1>Job</h1>Please complete the CAPTCHA to continue</body></html>"
        },
    )
    with pytest.raises(NeedsHuman) as e:
        CompanySiteAdapter(page, FAST).apply(
            CompanySiteAdapter(page, FAST).get_job.__self__.search(
                SearchCriteria(keywords=["x"], company_urls=[URL])
            )[0],
            ctx(tmp_path),
        )
    assert e.value.kind == "captcha"


def test_no_form_and_no_apply_button(page, tmp_path):
    serve(
        page, {"initech.test": "<html><body><h1>About us</h1><p>We make things.</p></body></html>"}
    )
    ad = CompanySiteAdapter(page, FAST)
    with pytest.raises(NeedsHuman):
        ad.apply(ad.get_job(URL), ctx(tmp_path))


class TestFieldMapper:
    FIELDS = [
        Field("1", "select", "Qualification", True, ["Bachelor's", "Master's"]),
        Field("2", "text", "Notice", True),
        Field("3", "radio", "Relocate?", True, ["Yes", "No"]),
    ]

    def test_filters_nulls_and_invalid_options(self):
        llm = FakeLLM({"values": {"1": "Bachelor's", "2": None, "3": "Perhaps", "99": "ghost"}})
        assert map_fields(llm, self.FIELDS, PROFILE) == {"1": "Bachelor's"}

    def test_matches_option_case_insensitively(self):
        llm = FakeLLM({"values": {"1": "master's", "2": " 30 days ", "3": "yes"}})
        assert map_fields(llm, self.FIELDS, PROFILE) == {
            "1": "Master's",
            "2": "30 days",
            "3": "Yes",
        }

    def test_bad_reply_raises_and_empty_skips_call(self):
        with pytest.raises(LLMError):
            map_fields(FakeLLM({"nope": 1}), self.FIELDS, PROFILE)
        llm = FakeLLM({})
        assert map_fields(llm, [], PROFILE) == {} and llm.calls == []
