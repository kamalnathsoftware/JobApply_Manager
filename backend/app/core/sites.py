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
    # extra cookies that also prove a login (site renames cookies now and then)
    alt_cookies: tuple[str, ...] = ()


SITES: dict[str, SiteInfo] = {
    "naukri": SiteInfo(
        "naukri", "Naukri", "https://www.naukri.com/nlogin/login", "nauk_at", "naukri.com", ("nauk_rt",)
    ),
    "linkedin": SiteInfo(
        "linkedin", "LinkedIn", "https://www.linkedin.com/login", "li_at", "linkedin.com"
    ),
    "indeed": SiteInfo("indeed", "Indeed", "https://secure.indeed.com/auth", "PPID", "indeed.com"),
    "company": SiteInfo("company", "Company site", "about:blank", None, None),
}
SITE_KEYS = tuple(SITES)
