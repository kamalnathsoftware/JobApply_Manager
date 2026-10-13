"""Indeed adapter -- 'Easily apply' (Indeed Apply) jobs only; jobs that redirect to a company
site are skipped (use the company-site adapter for those). Selectors live in SEL."""

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
from app.adapters.wizard import WizardSpec, run_wizard
from app.core.config import get_settings

SEL = {
    "card": "div.job_seen_beacon",
    "title": "h2.jobTitle a, a.jcs-JobTitle",
    "company": "[data-testid='company-name']",
    "location": "[data-testid='text-location']",
    "snippet": "[class*='snippet'], div.heading6 ul",
    "easy_badge": "[data-testid='indeedApply']",
    "detail_title": "h1",
    "detail_company": "[data-testid='inlineHeader-companyName'], [data-testid='jobsearch-CompanyInfoContainer'] a",
    "detail_desc": "#jobDescriptionText",
    "apply_btn": "#indeedApplyButton, button[data-testid='indeedApplyButton'], button:has-text('Apply now')",
    "external_btn": "#applyButtonLinkContainer a, a:has-text('Apply on company site'), button:has-text('Apply on company site')",
    "applied": ":text('You applied'), :text-is('Applied'), [data-testid='already-applied']",
    "form_root": "form, main",
    "upload_option": "button:has-text('Upload a resume'), label:has-text('Upload a resume')",
    "next": ["button[data-testid='continue-button']", "button:has-text('Continue')"],
    "submit": ["button:has-text('Submit your application')", "button[data-testid='submit-button']"],
    "done_text": "Your application has been submitted|Application submitted|post-apply",
}
_CARD_JS = """
(sel) => [...document.querySelectorAll(sel.card)].map(c => {
  const t = (s) => { const e = c.querySelector(s); return e ? e.innerText.replace(/\\s+/g,' ').trim() : null; };
  const a = c.querySelector(sel.title);
  return { id: a ? a.getAttribute('data-jk') : null, title: a ? a.innerText.trim() : null,
           company: t(sel.company), location: t(sel.location), snippet: t(sel.snippet),
           easy: !!c.querySelector(sel.easy_badge) || /easily apply/i.test(c.innerText) };
})
"""
MAX_PAGES = 5


def base_url() -> str:
    return get_settings().indeed_base_url.rstrip("/")


def build_search_url(c: SearchCriteria, start: int = 0) -> str:
    q = [f"q={quote_plus(' '.join(c.keywords))}", "sort=date", "sc=0kf%3Aattr%28DSQF7%29%3B"]
    if c.location:
        q.append(f"l={quote_plus(c.location)}")
    if c.posted_within_days:
        q.append(f"fromage={c.posted_within_days}")
    if start:
        q.append(f"start={start}")
    return f"{base_url()}/jobs?{'&'.join(q)}"


def job_id_from_url(url: str) -> str:
    m = re.search(r"[?&]jk=([0-9a-f]+)", url)
    return m.group(1) if m else re.sub(r"\W+", "", url)[-30:]


class IndeedAdapter(SiteAdapter):
    site = "indeed"

    def search(self, criteria: SearchCriteria) -> list[JobPosting]:
        jobs: dict[str, JobPosting] = {}
        for page_no in range(MAX_PAGES):
            self.goto(build_search_url(criteria, page_no * 10))
            try:
                self.page.wait_for_selector(SEL["card"], timeout=8000)
            except Exception:
                break
            cards = self.page.evaluate(_CARD_JS, SEL)
            before = len(jobs)
            for c in cards:
                if not c["id"] or not c["title"] or self.excluded(c["company"], criteria):
                    continue
                jobs.setdefault(
                    c["id"],
                    JobPosting(
                        site=self.site,
                        external_id=c["id"],
                        url=f"{base_url()}/viewjob?jk={c['id']}",
                        title=c["title"],
                        company=c["company"],
                        location=c["location"],
                        description=c["snippet"],
                        apply_type="easy" if c["easy"] else "unknown",
                    ),
                )
                if len(jobs) >= criteria.max_results:
                    return list(jobs.values())
            if len(jobs) == before:
                break
            self.h.pause(2.0, 5.0)
        return list(jobs.values())

    def _text(self, key: str) -> str | None:
        loc = self.page.locator(SEL[key]).first
        return loc.inner_text().strip() if loc.count() else None

    def get_job(self, url: str) -> JobPosting:
        self.goto(url)
        title = self._text("detail_title")
        if not title:
            raise AdapterError("job page not recognised (markup changed or page blocked)")
        has_apply = self.page.locator(SEL["apply_btn"]).count() > 0
        external = self.page.locator(SEL["external_btn"]).count() > 0 and not has_apply
        return JobPosting(
            site=self.site,
            external_id=job_id_from_url(url),
            url=url,
            title=title,
            company=self._text("detail_company"),
            description=self._text("detail_desc"),
            apply_type="external" if external else "easy",
            already_applied=self.page.locator(SEL["applied"]).first.count() > 0,
        )

    def _done(self) -> bool:
        body = self.page.evaluate("() => document.body.innerText.slice(0, 5000)")
        return bool(re.search(SEL["done_text"], body or "", re.I)) or "post-apply" in self.page.url

    def apply(self, job: JobPosting, ctx: ApplyContext) -> ApplyResult:
        def shot(n):
            return self.screenshot(ctx.screenshot_dir, f"indeed_{job.external_id}_{n}")

        self.goto(job.url)
        if self.page.locator(SEL["applied"]).first.count():
            return ApplyResult(ApplyStatus.ALREADY_APPLIED, "already applied")
        btn = self.page.locator(SEL["apply_btn"]).first
        if not btn.count():
            if self.page.locator(SEL["external_btn"]).count():
                return ApplyResult(
                    ApplyStatus.SKIPPED,
                    "applies on the company website (external)",
                    shot("external"),
                )
            raise AdapterError("apply button not found")
        self.h.click(btn)
        self.page.wait_for_load_state("domcontentloaded")
        self.h.pause(1.5, 3.0)
        self.check_blocked()
        if re.search(r"/auth|/account/login", self.page.url):
            raise NeedsHuman("login", "Indeed session expired - log in again")

        def choose_upload():
            opt = self.page.locator(SEL["upload_option"]).first
            if opt.count() and opt.is_visible():
                opt.click()

        spec = WizardSpec(
            root=SEL["form_root"].split(",")[0],
            next_buttons=SEL["next"],
            submit_buttons=SEL["submit"],
            is_done=self._done,
            on_step=choose_upload,
        )
        run_wizard(self.page, spec, ctx, self.h, shot)
        return ApplyResult(ApplyStatus.APPLIED, "applied via Indeed Apply", shot("applied"))
