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
        if BLOCK_TEXT.search(text or ""):
            return "bot-check text on page"
    except Exception:
        return None
    return None
