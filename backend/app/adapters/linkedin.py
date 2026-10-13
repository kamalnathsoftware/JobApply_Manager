"""LinkedIn adapter -- Easy Apply jobs ONLY (external 'Apply' jobs are skipped).

LinkedIn restricts automation in its User Agreement and aggressively checks for it; use this
at low volume, accept that your account may be limited, and never expect it to get past
verification (it stops with NeedsHuman). Selectors are best-effort and live in SEL."""

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

BASE = "https://www.linkedin.com"
SEL = {
    "card": "li[data-occludable-job-id], div.job-card-container[data-job-id]",
    "title": "a.job-card-list__title, a.job-card-container__link, a[href*='/jobs/view/']",
    "company": ".artdeco-entity-lockup__subtitle, .job-card-container__primary-description",
    "location": ".job-card-container__metadata-item, .artdeco-entity-lockup__caption",
    "detail_title": "h1",
    "detail_company": ".job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name",
    "detail_desc": "#job-details, .jobs-description__content",
    "apply_btn": "button.jobs-apply-button",
    "applied": ".artdeco-inline-feedback--success, :text('Application submitted'), :text-matches('^Applied ', 'i')",
    "modal": "div.jobs-easy-apply-modal, div[role='dialog'][aria-labelledby*='easy-apply']",
    "next": ["button[aria-label='Continue to next step']", "button[data-easy-apply-next-button]"],
    "review": ["button[aria-label='Review your application']"],
    "submit": ["button[aria-label='Submit application']"],
    "success": ":text('Application sent'), :text('Your application was sent'), #post-apply-modal",
    "dismiss": "button[aria-label='Dismiss']",
    "discard": "button[data-control-name='discard_application_confirm_btn'], button:has-text('Discard')",
    "follow": "input[id*='follow-company']",
}
EXPERIENCE_LEVEL = [(1, "2"), (3, "3"), (8, "4"), (15, "5")]  # years -> f_E code
JOB_TYPE = {
    "full_time": "F",
    "part_time": "P",
    "contract": "C",
    "internship": "I",
    "temporary": "T",
}


def build_search_url(c: SearchCriteria, start: int = 0) -> str:
    q = [f"keywords={quote_plus(' '.join(c.keywords))}", "f_AL=true", "sortBy=DD"]
    if c.location:
        q.append(f"location={quote_plus(c.location)}")
    if c.posted_within_days:
        q.append(f"f_TPR=r{c.posted_within_days * 86400}")
    if c.experience_min is not None:
        code = next((code for limit, code in EXPERIENCE_LEVEL if c.experience_min <= limit), "5")
        q.append(f"f_E={code}")
    if c.job_type in JOB_TYPE:
        q.append(f"f_JT={JOB_TYPE[c.job_type]}")
    if start:
        q.append(f"start={start}")
    return f"{BASE}/jobs/search/?{'&'.join(q)}"


def job_id_from_url(url: str) -> str:
    m = re.search(r"/jobs/view/(?:[\w-]*?-)?(\d{4,})", url) or re.search(r"currentJobId=(\d+)", url)
    return m.group(1) if m else re.sub(r"\W+", "", url)[-30:]


_CARD_JS = """
(sel) => [...document.querySelectorAll(sel.card)].map(c => {
  const t = (s) => { const e = c.querySelector(s); return e ? e.innerText.replace(/\\s+/g,' ').trim() : null; };
  const a = c.querySelector(sel.title);
  return { id: c.getAttribute('data-occludable-job-id') || c.getAttribute('data-job-id'),
           href: a ? a.getAttribute('href') : null, title: a ? (a.getAttribute('aria-label') || a.innerText).trim() : null,
           company: t(sel.company), location: t(sel.location) };
})
"""


class LinkedInAdapter(SiteAdapter):
    site = "linkedin"

    def _guard_auth(self) -> None:
        url = self.page.url
        if re.search(r"/checkpoint|/challenge", url):
            raise NeedsHuman("captcha", "LinkedIn security verification required")
        if re.search(r"/login|/authwall|/uas/", url):
            raise NeedsHuman("login", "LinkedIn session expired - log in again")

    def goto(self, url: str) -> None:
        super().goto(url)
        self._guard_auth()

    def search(self, criteria: SearchCriteria) -> list[JobPosting]:
        jobs: dict[str, JobPosting] = {}
        for start in range(0, 100, 25):
            self.goto(build_search_url(criteria, start))
            try:
                self.page.wait_for_selector(SEL["card"], timeout=8000)
            except Exception:
                break
            cards = self.page.evaluate(_CARD_JS, SEL)
            if not cards:
                break
            before = len(jobs)
            for c in cards:
                if not c["id"] or not c["title"] or self.excluded(c["company"], criteria):
                    continue
                jobs.setdefault(
                    c["id"],
                    JobPosting(
                        site=self.site,
                        external_id=c["id"],
                        url=f"{BASE}/jobs/view/{c['id']}/",
                        title=c["title"],
                        company=c["company"],
                        location=c["location"],
                        apply_type="easy",  # the f_AL=true filter only returns Easy Apply jobs
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

    def _is_easy_apply(self) -> bool:
        btn = self.page.locator(SEL["apply_btn"]).first
        if not btn.count():
            return False
        label = f"{btn.get_attribute('aria-label') or ''} {btn.inner_text()}"
        return "easy apply" in label.lower()

    def get_job(self, url: str) -> JobPosting:
        self.goto(url)
        title = self._text("detail_title")
        if not title:
            raise AdapterError("job page not recognised (markup changed or page blocked)")
        return JobPosting(
            site=self.site,
            external_id=job_id_from_url(url),
            url=url,
            title=title,
            company=self._text("detail_company"),
            description=self._text("detail_desc"),
            apply_type="easy" if self._is_easy_apply() else "external",
            already_applied=self.page.locator(SEL["applied"]).first.count() > 0,
        )

    def apply(self, job: JobPosting, ctx: ApplyContext) -> ApplyResult:
        def shot(n):
            return self.screenshot(ctx.screenshot_dir, f"linkedin_{job.external_id}_{n}")

        self.goto(job.url)
        if self.page.locator(SEL["applied"]).first.count():
            return ApplyResult(ApplyStatus.ALREADY_APPLIED, "already applied")
        if not self._is_easy_apply():
            return ApplyResult(
                ApplyStatus.SKIPPED,
                "not an Easy Apply job (external application)",
                shot("external"),
            )
        self.h.click(self.page.locator(SEL["apply_btn"]).first)
        self.h.pause(1.0, 2.0)
        self.check_blocked()
        self._guard_auth()
        if not self.page.locator(SEL["modal"]).first.count():
            raise AdapterError("Easy Apply dialog did not open")

        def unfollow():
            box = self.page.locator(SEL["follow"]).first
            if box.count() and box.is_checked():
                box.uncheck(force=True)

        spec = WizardSpec(
            root=SEL["modal"].split(",")[0],
            next_buttons=SEL["next"] + SEL["review"],
            submit_buttons=SEL["submit"],
            is_done=lambda: self.page.locator(SEL["success"]).first.count() > 0,
            before_submit=unfollow,
        )
        submitted = False
        try:
            run_wizard(self.page, spec, ctx, self.h, shot)
            submitted = True
            result = ApplyResult(ApplyStatus.APPLIED, "applied via Easy Apply", shot("applied"))
            dismiss = self.page.locator(SEL["dismiss"]).first
            if dismiss.count():
                dismiss.click()
            return result
        finally:
            if not submitted:
                self._discard_draft()

    def _discard_draft(self) -> None:
        """Close the dialog without leaving a half-filled saved application behind."""
        try:
            dismiss = self.page.locator(SEL["dismiss"]).first
            if dismiss.count():
                dismiss.click()
                discard = self.page.locator(SEL["discard"]).first
                if discard.count():
                    discard.click()
        except Exception:
            pass
