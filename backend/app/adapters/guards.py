"""Detects bot-checks / CAPTCHAs so automation can stop and hand over to a human.
Detection only -- nothing here tries to solve or bypass them."""

import re

CAPTCHA_FRAME = re.compile(
    r"recaptcha|hcaptcha|captcha|challenges\.cloudflare|arkoselabs|funcaptcha", re.I
)
BLOCK_TEXT = re.compile(
    r"verify (that )?you are (a )?human|are you a robot|unusual (traffic|activity)|"
    r"complete the (captcha|security check)|security verification|checking your browser|"
    r"press (and|&) hold|access denied|temporarily blocked",
    re.I,
)

MAX_BLOCK_PAGE_CHARS = 1500


def detect_block(page) -> str | None:
    try:
        for fr in page.frames:
            if fr is not page.main_frame and CAPTCHA_FRAME.search(fr.url or ""):
                return "captcha challenge frame present"
        if page.locator(
            "[class*='captcha' i]:visible, #captcha:visible, .g-recaptcha:visible"
        ).count():
            return "captcha element visible"
        text = page.evaluate("() => (document.body ? document.body.innerText : '').slice(0, 4000)")
        m = BLOCK_TEXT.search(text or "")
        # real block pages are nearly empty; a long page that merely contains the phrase is content
        if m and len(text.strip()) < MAX_BLOCK_PAGE_CHARS:
            return f"bot-check text on page: '{m.group(0)}' ({(page.url or '')[:80]})"
    except Exception:
        return None
    return None


_LOGIN_TEXT = re.compile(
    r"(sign in|log ?in|login) (or [\w ]+ )?to (apply|continue|submit)|please (sign in|log ?in)|"
    r"you (must|need to) (be )?(signed|logged) in",
    re.I,
)
_ACCOUNT_TEXT = re.compile(
    r"create (an |your )?account|register (to|for|an account)|sign up (to|for)|"
    r"you (must|need to) (create|have) an account|candidate (registration|portal)",
    re.I,
)


def detect_gate(page) -> tuple[str, str] | None:
    """Detects login / account-creation walls on a company career page.
    Returns (kind, detail) with kind in {"login", "account_required"} or None."""
    try:
        info = page.evaluate(
            """() => {
              const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
              const inputs = [...document.querySelectorAll('input,select,textarea')].filter(vis)
                .filter(e => !['hidden','submit','button','checkbox','radio'].includes(e.type));
              return { pw: inputs.filter(e => e.type === 'password').length, n: inputs.length,
                       text: (document.body ? document.body.innerText : '').slice(0, 6000) };
            }"""
        )
    except Exception:
        return None
    text = info["text"] or ""
    if info["pw"]:
        if _ACCOUNT_TEXT.search(text) and info["pw"] >= 1 and info["n"] <= 8:
            return "account_required", "account creation is required before applying"
        return "login", "a login is required before applying"
    if _ACCOUNT_TEXT.search(text) and re.search(
        r"(to|before) apply|apply.{0,40}account", text, re.I
    ):
        return "account_required", "an account is required before applying"
    if _LOGIN_TEXT.search(text) and info["n"] <= 3:
        return "login", "a login is required before applying"
    return None
