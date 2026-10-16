from app.workers.assisted_login import prefill_login
from tests.conftest import serve


def test_prefill_types_saved_credentials_and_submits(page):
    serve(page, {"naukri.com": "naukri_login.html"})
    page.goto("https://www.naukri.com/nlogin/login")
    out = prefill_login(page, "naukri", "me@example.com", "s3cret-pw")
    assert out.startswith("filled and submitted")
    assert page.evaluate("window.__submitted") == {"u": "me@example.com", "p": "s3cret-pw"}
    assert "s3cret" not in out and "me@example" not in out  # outcome text never leaks values


def test_prefill_without_password_only_fills_email_and_can_skip_submit(page):
    serve(page, {"naukri.com": "naukri_login.html"})
    page.goto("https://www.naukri.com/nlogin/login")
    assert prefill_login(page, "naukri", "me@example.com", None, submit=False) == "filled"
    assert page.input_value("#usernameField") == "me@example.com"
    assert page.input_value("#passwordField") == ""
    assert page.evaluate("window.__submitted") is None


def test_prefill_skips_when_no_email_or_no_form_or_bot_check(page):
    serve(page, {"naukri.com": "naukri_login.html"})
    page.goto("https://www.naukri.com/nlogin/login")
    assert prefill_login(page, "naukri", None, "x").startswith("skipped: no saved email")
    assert prefill_login(page, "company", "me@example.com", "x").startswith("skipped")
    page.unroute_all()
    serve(page, {"naukri.com": "<html><body>Please verify you are human</body></html>"})
    page.goto("https://www.naukri.com/nlogin/login")
    assert "bot check" in prefill_login(page, "naukri", "me@example.com", "x")
    page.unroute_all()
    serve(page, {"naukri.com": "<html><body><h1>Maintenance</h1></body></html>"})
    page.goto("https://www.naukri.com/nlogin/login")
    page.set_default_timeout(500)
    assert "not found" in prefill_login(page, "naukri", "me@example.com", "x")
