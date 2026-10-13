"""Multi-step 'Easy Apply' style forms (LinkedIn, Indeed, ...): fill what we can, click
Next/Continue/Review, stop for a human on any required field we cannot answer."""

from collections.abc import Callable
from dataclasses import dataclass

from app.adapters.base import AdapterError, ApplyContext, NeedsHuman
from app.adapters.forms import extract_fields, fill_form
from app.adapters.humanize import Humanizer


@dataclass
class WizardSpec:
    root: str  # selector of the form container (modal / form)
    next_buttons: list[str]  # tried in order each step
    submit_buttons: list[str]
    is_done: Callable[[], bool]  # True once the site confirmed the submission
    before_submit: Callable[[], None] | None = None  # e.g. untick "follow company"
    on_step: Callable[[], None] | None = None  # e.g. pick "upload resume" option
    max_steps: int = 12


def _first_visible(scope, selectors: list[str]):
    for sel in selectors:
        loc = scope.locator(sel).first
        if loc.count() and loc.is_visible() and loc.is_enabled():
            return loc
    return None


def run_wizard(scope, spec: WizardSpec, ctx: ApplyContext, h: Humanizer, shot) -> None:
    """Drive the wizard to completion. `scope` is a Page or Frame. Raises NeedsHuman for any
    required field without a known answer, AdapterError if the flow does not progress."""
    last_signature = None
    for _ in range(spec.max_steps):
        if spec.is_done():
            return
        if spec.on_step:
            spec.on_step()
        fields = extract_fields(scope, spec.root)
        rep = fill_form(scope, ctx.resolver, ctx.resume_path, h, spec.root, fields=fields)
        if rep.unknown:
            shot("question")
            labels = "; ".join(f.label or f.type for f in rep.unknown)
            raise NeedsHuman("unknown_question", labels)
        submit = _first_visible(scope, spec.submit_buttons)
        if submit is not None:
            if spec.before_submit:
                spec.before_submit()
            h.click(submit)
            h.pause(1.0, 2.5)
            if spec.is_done():
                return
            raise AdapterError("submitted but no confirmation was shown")
        nxt = _first_visible(scope, spec.next_buttons)
        if nxt is None:
            raise AdapterError("no Next/Submit button found (markup changed?)")
        signature = (tuple(f.label for f in fields), tuple(sorted(rep.filled)))
        if signature == last_signature:
            shot("stuck")
            raise NeedsHuman("unknown_field", "form did not advance - needs manual input")
        last_signature = signature
        h.click(nxt)
        h.pause(0.8, 1.8)
    raise AdapterError("application wizard exceeded the step limit")
