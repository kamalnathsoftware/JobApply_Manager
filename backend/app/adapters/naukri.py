"""Naukri adapter.

NOTE: Naukri changes its markup regularly and these selectors cannot be verified from CI (we
never touch the real site in tests). If searching/applying stops working, adjust SEL below --
all site-specific selectors live in that one dict."""

import re
from urllib.parse import quote_plus

from app.adapters.base import (
    AdapterError,
    ApplyContext,
    ApplyResult,
    ApplyStatus,
    JobPosting,
    NeedsHuman,
    SearchCriteria,
    SiteAdapter,
)

SEL = {
    "card": "div.srp-jobtuple-wrapper",
    "title": "a.title",
    "company": "a.comp-name",
    "experience": "span.exp-wrap",
    "salary": "span.sal-wrap",
    "location": "span.loc-wrap",
    "snippet": "span.job-desc",
    "posted": "span.job-post-day",
    "detail_title": "h1, header h1",
    "detail_company": "a[class*='comp-name'], div[class*='jd-header-comp-name'] a",
    "detail_desc": "div[class*='dang-inner-html'], section[class*='job-desc']",
    "apply_btn": "#apply-button",
    "external_btn": "#company-site-button",
    "applied_marker": "#already-applied, .already-applied, button:has-text('Already Applied')",
    "login_layer": "#login_Layer, .login-layer",
    # The screening-question bot. EVERYTHING below it is looked up inside this container only:
    # the job page has its own "Save" (save job) button that must never be mistaken for the bot's.
    "chatbot": (
        "div[class*='chatBotContainer' i], div[id$='ChatBotContainer'], "
        "div[class*='chatbot_DrawerContentWrapper'], div.chatbot_Drawer"
    ),
    "bot_msg": "div.botMsg, li.botItem .botMsg",
    "chip": "div.ssrc__radio-btn-container label, div.chatbot_Chip",
    "answer_box": "div.textArea[contenteditable='true'], input[type='text']",
    "send": "div.sendMsg, button:has-text('Save'), button:has-text('Submit'), button:has-text('Send')",
}
SUCCESS_RE = re.compile(
    r"successfully applied|you have (successfully )?applied|application (was )?(sent|submitted)|"
    r"applied successfully|applied to\b|thank you for applying",
    re.I,
)
# After a one-click apply Naukri lands on an "Apply Confirmation" page (often in a new tab).
CONFIRM_URL_RE = re.compile(r"/myapply/|apply[-_]?confirm|applyconfirm", re.I)
CONFIRM_TITLE_RE = re.compile(r"apply confirmation|application (sent|submitted)|applied", re.I)
MAX_BOT_STEPS = 15
MAX_PAGES = 10
RESULT_WAIT_S = 12.0

_CARD_JS = """
(sel) => [...document.querySelectorAll(sel.card)].map(c => {
  const t = (s) => { const e = c.querySelector(s); return e ? e.innerText.replace(/\\s+/g,' ').trim() : null; };
  const a = c.querySelector(sel.title);
  return { id: c.getAttribute('data-job-id'), url: a ? a.href : null, title: a ? a.innerText.trim() : null,
    company: t(sel.company), experience: t(sel.experience), salary: t(sel.salary),
    location: t(sel.location), snippet: t(sel.snippet), posted: t(sel.posted) };
})
"""


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def build_search_url(c: SearchCriteria, page_no: int = 1) -> str:
    kw = ", ".join(c.keywords)
    path = f"{slug(' '.join(c.keywords))}-jobs"
    if c.location:
        path += f"-in-{slug(c.location)}"
    if page_no > 1:
        path += f"-{page_no}"
    q = [f"k={quote_plus(kw)}"]
    if c.location:
        q.append(f"l={quote_plus(c.location)}")
    if c.experience_min is not None:
        q.append(f"experience={c.experience_min}")
    if c.posted_within_days:
        q.append(f"jobAge={c.posted_within_days}")
    if c.salary_min:
        # Naukri filters salary in lakhs per annum
        q.append(f"salary={max(1, c.salary_min // 100000)}")
    return f"https://www.naukri.com/{path}?{'&'.join(q)}"


def job_id_from_url(url: str) -> str:
    m = re.search(r"-(\d{6,})(?:\?|$)", url) or re.search(r"(\d{6,})", url)
    return m.group(1) if m else slug(url)[-40:]


class NaukriAdapter(SiteAdapter):
    site = "naukri"

    # ---- search ------------------------------------------------------------------
    def search(self, criteria: SearchCriteria) -> list[JobPosting]:
        jobs: dict[str, JobPosting] = {}
        for page_no in range(1, MAX_PAGES + 1):
            self.goto(build_search_url(criteria, page_no))
            try:
                self.page.wait_for_selector(SEL["card"], timeout=8000)
            except Exception:
                break  # no results (or markup changed)
            cards = self.page.evaluate(_CARD_JS, SEL)
            if not cards:
                break
            for c in cards:
                if not c["url"] or not c["title"] or self.excluded(c["company"], criteria):
                    continue
                jid = c["id"] or job_id_from_url(c["url"])
                jobs.setdefault(
                    jid,
                    JobPosting(
                        site=self.site,
                        external_id=jid,
                        url=c["url"],
                        title=c["title"],
                        company=c["company"],
                        location=c["location"],
                        salary=c["salary"],
                        experience=c["experience"],
                        description=c["snippet"],
                        posted=c["posted"],
                    ),
                )
                if len(jobs) >= criteria.max_results:
                    return list(jobs.values())
            self.h.pause(2.0, 5.0)
        return list(jobs.values())

    # ---- detail ---------------------------------------------------------------------
    def _text(self, key: str) -> str | None:
        loc = self.page.locator(SEL[key]).first
        return loc.inner_text().strip() if loc.count() else None

    def get_job(self, url: str) -> JobPosting:
        self.goto(url)
        title = self._text("detail_title")
        if not title:
            raise AdapterError("job page not recognised (markup changed or page blocked)")
        loc = self.page.locator(SEL["applied_marker"]).first
        applied = loc.count() > 0 and loc.is_visible()
        external = (
            self.page.locator(SEL["external_btn"]).count() > 0
            and not self.page.locator(SEL["apply_btn"]).count()
        )
        return JobPosting(
            site=self.site,
            external_id=job_id_from_url(url),
            url=url,
            title=title,
            company=self._text("detail_company"),
            description=self._text("detail_desc"),
            apply_type="external" if external else "easy",
            already_applied=applied,
        )

    # ---- apply ------------------------------------------------------------------------
    def _chat(self, key: str):
        """Locator for a bot element, searched inside the bot container only."""
        return self.page.locator(SEL["chatbot"]).locator(SEL[key])

    def _page_confirms(self, pg) -> bool:
        try:
            if CONFIRM_URL_RE.search(pg.url or "") or CONFIRM_TITLE_RE.search(pg.title() or ""):
                return True
            if pg.locator(SEL["applied_marker"]).first.count():
                return True
            body = pg.evaluate(
                "() => (document.body ? document.body.innerText : '').slice(0, 5000)"
            )
            return bool(SUCCESS_RE.search(body or ""))
        except Exception:  # page navigating / closing
            return False

    def _applied(self) -> bool:
        """True when this tab - or a tab the apply click opened - shows the confirmation."""
        for pg in list(self.page.context.pages):
            if self._page_confirms(pg):
                return True
        return False

    def _close_extra_tabs(self) -> None:
        for pg in list(self.page.context.pages):
            if pg is not self.page:
                try:
                    pg.close()
                except Exception:
                    pass

    def _wait_outcome(self, timeout_s: float = RESULT_WAIT_S) -> str:
        """After clicking Apply: wait for 'applied', a 'chatbot' with questions, or give up."""
        waited = 0.0
        while waited < timeout_s:
            if self._applied():
                return "applied"
            if self.page.locator(SEL["chatbot"]).first.count():
                return "chatbot"
            self.page.wait_for_timeout(500)
            waited += 0.5
        return "none"

    def apply(self, job: JobPosting, ctx: ApplyContext) -> ApplyResult:
        self.goto(job.url)
        shot = lambda n: self.screenshot(ctx.screenshot_dir, f"naukri_{job.external_id}_{n}")  # noqa: E731
        if self.page.locator(SEL["applied_marker"]).first.count():
            return ApplyResult(ApplyStatus.ALREADY_APPLIED, "already applied")
        btn = self.page.locator(SEL["apply_btn"]).first
        if not btn.count():
            if self.page.locator(SEL["external_btn"]).count():
                return ApplyResult(
                    ApplyStatus.SKIPPED,
                    "applies on the company website (external)",
                    shot("external"),
                )
            if self.page.locator(SEL["login_layer"]).first.count():
                raise NeedsHuman("login", "Naukri session expired - log in again")
            raise AdapterError("apply button not found")
        self.h.click(btn)
        self.h.pause(1.0, 2.5)
        self.check_blocked()
        if self.page.locator(SEL["login_layer"]).first.is_visible():
            raise NeedsHuman("login", "Naukri session expired - log in again")
        outcome = self._wait_outcome()
        for _ in range(MAX_BOT_STEPS):
            if outcome == "applied":
                self._close_extra_tabs()
                return ApplyResult(ApplyStatus.APPLIED, "applied", shot("applied"))
            if outcome != "chatbot":
                break
            self._answer_next_question(ctx, shot)
            outcome = self._wait_outcome(timeout_s=6.0)
        if outcome == "applied" or self._applied():
            self._close_extra_tabs()
            return ApplyResult(ApplyStatus.APPLIED, "applied", shot("applied"))
        shot("unconfirmed")
        raise AdapterError(
            "clicked Apply but Naukri showed no confirmation (see the saved screenshot) - "
            "check the job manually"
        )

    def _answer_next_question(self, ctx: ApplyContext, shot) -> None:
        msgs = self._chat("bot_msg")
        question = msgs.last.inner_text().strip() if msgs.count() else ""
        chips = self._chat("chip")
        options = [chips.nth(i).inner_text().strip() for i in range(chips.count())]
        answer = ctx.resolver.resolve(question, options or None)
        if answer is None:
            shot("question")
            raise NeedsHuman("unknown_question", question or "(unreadable screening question)")
        if options:
            chips.nth(options.index(answer)).click()
        else:
            box = self._chat("answer_box").first
            if not box.count():
                raise NeedsHuman("unknown_field", question)
            box.click()
            box.press_sequentially(answer, delay=self.h.rng.randint(35, 90))
        self.h.pause(0.5, 1.2)
        send = self._chat("send").first
        if send.count():
            send.click(timeout=8000)
        self._wait_for_next(question)

    def _wait_for_next(self, previous_question: str, timeout_s: float = 8.0) -> None:
        """Wait until the bot shows a different message, closes, or the apply is confirmed."""
        waited = 0.0
        while waited < timeout_s:
            msgs = self._chat("bot_msg")
            current = msgs.last.inner_text().strip() if msgs.count() else ""
            if current != previous_question or not self.page.locator(SEL["chatbot"]).count():
                break
            self.page.wait_for_timeout(250)
            waited += 0.25
        self.h.pause(0.5, 1.5)
