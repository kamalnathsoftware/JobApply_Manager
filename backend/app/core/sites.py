"""Static per-site configuration shared by assisted login and the adapters."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SiteInfo:
    key: str
    name: str
    login_url: str
    # Cookie that only exists once the user is logged in; None = cannot auto-detect.
    session_cookie: str | None
    cookie_domain: str | None
    # Regex matching page URLs that only a logged-in user reaches (second login signal).
    logged_in_url: str | None = None
    # Login-form selectors (first visible match wins) used to pre-fill saved credentials.
    user_selectors: tuple[str, ...] = ()
    pass_selectors: tuple[str, ...] = ()
    submit_selectors: tuple[str, ...] = ()


SITES: dict[str, SiteInfo] = {
    "naukri": SiteInfo(
        "naukri",
        "Naukri",
        "https://www.naukri.com/nlogin/login",
        "nauk_at",
        "naukri.com",
        logged_in_url=r"naukri\.com/(mnjuser|myhome)",
        user_selectors=("#usernameField", "input[placeholder*='Email' i]", "input[type='text']"),
        pass_selectors=("#passwordField", "input[type='password']"),
        submit_selectors=(
            "button.loginButton",
            "button[type='submit']",
            "button:has-text('Login')",
        ),
    ),
    "linkedin": SiteInfo(
        "linkedin",
        "LinkedIn",
        "https://www.linkedin.com/login",
        "li_at",
        "linkedin.com",
        logged_in_url=r"linkedin\.com/(feed|jobs|mynetwork|messaging|in/)",
        user_selectors=("#username", "input[name='session_key']"),
        pass_selectors=("#password", "input[name='session_password']"),
        submit_selectors=("button[type='submit']",),
    ),
    "indeed": SiteInfo(
        "indeed",
        "Indeed",
        "https://secure.indeed.com/auth",
        "PPID",
        "indeed.com",
        logged_in_url=r"^https://(www|[a-z]{2,3})\.indeed\.com/",
        user_selectors=("input[type='email']", "input[name='__email']"),
        pass_selectors=("input[type='password']",),
        submit_selectors=("button[type='submit']", "button:has-text('Continue')"),
    ),
    "company": SiteInfo("company", "Company site", "about:blank", None, None),
}
SITE_KEYS = tuple(SITES)
