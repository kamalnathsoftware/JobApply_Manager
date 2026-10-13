"""Generic company career-site adapter.

Opens an apply URL, finds the application form, fills it from the parsed resume (resume data
first, then LLM-assisted field mapping), uploads the resume and submits. It will NOT guess:
unknown required fields, logins, account creation, consent checkboxes and CAPTCHAs all stop
the attempt with NeedsHuman + a screenshot."""

import hashlib
import re
from urllib.parse import urlparse

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
from app.adapters.forms import extract_fields, fill_form, fill_value
from app.adapters.guards import detect_gate
from app.services.field_mapper import map_fields
from app.services.llm import LLMError

SEL = {
    "apply_entry": "a:has-text('Apply now'), button:has-text('Apply now'), a:has-text('Apply for this job'), "
    "button:has-text('Apply for this job'), a:has-text('Apply'), button:has-text('Apply')",
    "next": [
        "button:has-text('Next')",
        "button:has-text('Continue')",
        "button:has-text('Save and continue')",
    ],
    "submit": [
        "button:has-text('Submit application')",
        "button:has-text('Submit Application')",
        "button:has-text('Send application')",
        "button[type='submit']:has-text('Submit')",
        "button:has-text('Submit')",
        "input[type='submit']",
        "button:has-text('Apply')",
    ],
}
SUCCESS_RE = re.compile(
    r"thank you for (applying|your application)|application (has been |was )?(received|submitted|sent)|"
    r"successfully (applied|submitted)|we(’|')?ve received your application",
    re.I,
)
SUCCESS_URL_RE = re.compile(r"thank|confirmation|success|submitted", re.I)
MAX_STEPS = 8
_PICK_FORM_JS = """
() => {
  const vis = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  let best = null, bestN = 0;
  document.querySelectorAll('form').forEach(f => {
    const n = [...f.querySelectorAll('input,select,textarea')].filter(e =>
      !['hidden','submit','button','search'].includes(e.type) && (vis(e) || e.type === 'file')).length;
    if (n > bestN) { best = f; bestN = n; }
  });
  document.querySelectorAll('[data-jam-root]').forEach(e => e.removeAttribute('data-jam-root'));
  if (best && bestN >= 1) { best.setAttribute('data-jam-root', '1'); return '[data-jam-root="1"]'; }
  return 'body';
}
"""


def job_id_for(url: str) -> str:
    return hashlib.sha1(url.strip().encode()).hexdigest()[:16]


class CompanySiteAdapter(SiteAdapter):
    site = "company"

    # -- "search" is just the list of career URLs the user supplied -------------------------
    def search(self, criteria: SearchCriteria) -> list[JobPosting]:
        jobs = []
        for url in criteria.company_urls[: criteria.max_results]:
            host = urlparse(url).netloc
            jobs.append(
                JobPosting(
                    site=self.site,
                    external_id=job_id_for(url),
                    url=url,
                    title=f"Application at {host}",
                    company=host,
                    apply_type="easy",
                )
            )
        return jobs

    def get_job(self, url: str) -> JobPosting:
        self.goto(url)
        title = ""
        h1 = self.page.locator("h1").first
        if h1.count():
            title = h1.inner_text().strip()
        title = title or self.page.title() or urlparse(url).netloc
        text = self.page.evaluate(
            "() => (document.body ? document.body.innerText : '').slice(0, 12000)"
        )
        return JobPosting(
            site=self.site,
            external_id=job_id_for(url),
            url=url,
            title=title[:500],
            company=urlparse(url).netloc,
            description=text,
            apply_type="easy",
        )

    # -- apply -------------------------------------------------------------------------------
    def _gate(self, shot) -> None:
        gate = detect_gate(self.page)
        if gate:
            kind, detail = gate
            shot(kind)
            raise NeedsHuman(kind, detail)

    def _active_page(self):
        """An 'Apply' click may open the form in a new tab."""
        pages = self.page.context.pages
        if pages and pages[-1] != self.page:
            self.page = pages[-1]
            self.page.wait_for_load_state("domcontentloaded")
        return self.page

    def _has_form(self) -> bool:
        """True once at least two visible, real form inputs are on screen (a lone search box
        or a hidden file input does not count)."""
        visible = [
            f
            for f in extract_fields(self.page, "body")
            if f.type not in ("search", "checkbox", "file")
        ]
        return len(visible) >= 2

    def _success(self) -> bool:
        body = self.page.evaluate(
            "() => (document.body ? document.body.innerText : '').slice(0, 6000)"
        )
        return bool(SUCCESS_RE.search(body or "")) or bool(SUCCESS_URL_RE.search(self.page.url))

    def apply(self, job: JobPosting, ctx: ApplyContext) -> ApplyResult:
        def shot(n):
            return self.screenshot(ctx.screenshot_dir, f"company_{job.external_id}_{n}")

        self.goto(job.url)
        self._gate(shot)
        if not self._has_form():
            entry = self.page.locator(SEL["apply_entry"]).first
            if not entry.count():
                raise NeedsHuman("unknown_field", "no application form or Apply button found")
            self.h.click(entry)
            self.page.wait_for_timeout(500)
            self._active_page()
            self.h.pause(1.0, 2.0)
            self.check_blocked()
            self._gate(shot)

        for _ in range(MAX_STEPS):
            root = self.page.evaluate(_PICK_FORM_JS)
            fields = extract_fields(self.page, root)
            if not fields:
                raise AdapterError("application form has no fillable fields")
            rep = fill_form(self.page, ctx.resolver, ctx.resume_path, self.h, root, fields=fields)
            unknown = [f for f in rep.unknown if f.type != "file"]
            if unknown and ctx.llm is not None:
                try:
                    mapped = map_fields(ctx.llm, unknown, ctx.profile, ctx.bank)
                except LLMError:
                    mapped = {}
                still = []
                for f in unknown:
                    if f.id in mapped and fill_value(self.page, f, mapped[f.id], self.h):
                        continue
                    still.append(f)
                unknown = still
            if unknown or [f for f in rep.unknown if f.type == "file"]:
                shot("unknown_field")
                labels = "; ".join(
                    f.label or f.type for f in rep.unknown if f.type != "file" or True
                )
                raise NeedsHuman("unknown_question", labels)
            self.check_blocked()

            submit = self._first(SEL["submit"])
            nxt = self._first(SEL["next"])
            btn = nxt if nxt is not None else submit
            if btn is None:
                raise AdapterError("no Next/Submit button found")
            is_submit = nxt is None
            self.h.click(btn)
            self.page.wait_for_timeout(500)
            self.h.pause(1.0, 2.5)
            self.check_blocked()
            if is_submit:
                if self._success():
                    return ApplyResult(
                        ApplyStatus.APPLIED, "submitted on company site", shot("applied")
                    )
                self._gate(shot)
                raise AdapterError("submitted but no confirmation page/message was detected")
        raise AdapterError("application flow exceeded the step limit")

    def _first(self, selectors: list[str]):
        for sel in selectors:
            loc = self.page.locator(sel).first
            if loc.count() and loc.is_visible() and loc.is_enabled():
                return loc
        return None
