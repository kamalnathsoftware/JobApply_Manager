"""Generic form discovery + filling shared by every adapter."""

from dataclasses import dataclass, field

from app.adapters.humanize import Humanizer
from app.services.answers import QuestionResolver, match_option

INSPECT_JS = r"""
(rootSel) => {
  document.querySelectorAll('[data-jam]').forEach(e => e.removeAttribute('data-jam'));  // ids are per-extraction
  const root = document.querySelector(rootSel) || document.body;
  const vis = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const txt = el => ((el && (el.innerText || el.textContent)) || '').replace(/\s+/g, ' ').trim();
  const labelOf = el => {
    const al = el.getAttribute('aria-label'); if (al) return al.trim();
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = lb.split(/\s+/).map(i => txt(document.getElementById(i))).join(' ').trim(); if (t) return t; }
    if (el.id) { const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]'); if (l) return txt(l); }
    const w = el.closest('label'); if (w) return txt(w);
    return el.placeholder || el.name || '';
  };
  const groupLabel = el => {
    const fs = el.closest('fieldset'); if (fs) { const lg = fs.querySelector('legend'); if (lg) return txt(lg); }
    const rg = el.closest('[role=radiogroup],[role=group]');
    if (rg) { const a = rg.getAttribute('aria-label'); if (a) return a;
      const l = rg.getAttribute('aria-labelledby'); if (l) return txt(document.getElementById(l)); }
    const c = el.closest('div'); const p = c && c.parentElement;
    if (p) { const h = p.querySelector('legend,label:not(:has(input)),span.question,.question,p'); if (h) return txt(h); }
    return '';
  };
  const out = [], groups = {}; let n = 0;
  root.querySelectorAll('input,select,textarea').forEach(el => {
    const tag = el.tagName.toLowerCase();
    const type = tag === 'input' ? (el.type || 'text').toLowerCase() : tag;
    if (['hidden', 'submit', 'button', 'image', 'reset'].includes(type) || el.disabled) return;
    if (type !== 'file' && !vis(el)) return;
    const required = el.required || el.getAttribute('aria-required') === 'true';
    if (type === 'radio') {
      const key = el.name || ('anon' + n);
      let g = groups[key];
      if (!g) { g = groups[key] = { id: String(n++), type: 'radio', label: groupLabel(el) || key,
        required, options: [], value: '' }; out.push(g); }
      const i = g.options.length;
      g.options.push(labelOf(el) || el.value);
      el.setAttribute('data-jam', g.id + '_' + i);
      if (el.checked) g.value = g.options[i];
      return;
    }
    const f = { id: String(n++), type, label: (labelOf(el) || '').replace(/\s*\*\s*$/, ''), required,
      options: [], value: '' };
    if (/\*\s*$/.test(labelOf(el) || '')) f.required = true;
    el.setAttribute('data-jam', f.id);
    if (tag === 'select') { f.options = [...el.options].filter(o => o.value !== '' || o.text.trim())
        .map(o => o.text.trim()); f.value = el.selectedOptions[0] && el.value ? el.selectedOptions[0].text.trim() : ''; }
    else if (type === 'checkbox') { f.value = el.checked ? 'true' : ''; }
    else if (type !== 'file') { f.value = el.value || ''; }
    out.push(f);
  });
  return out;
}
"""

TEXTLIKE = {"text", "email", "tel", "number", "url", "textarea", "search", "date", "password"}


@dataclass
class Field:
    id: str
    type: str
    label: str
    required: bool = False
    options: list[str] = field(default_factory=list)
    value: str = ""


@dataclass
class FillReport:
    filled: dict[str, str] = field(default_factory=dict)  # label -> value (never for passwords)
    unknown: list[Field] = field(default_factory=list)  # required fields we could not answer
    skipped: list[str] = field(default_factory=list)


def extract_fields(scope, root: str = "body") -> list[Field]:
    raw = scope.evaluate(INSPECT_JS, root)
    return [
        Field(**{k: r.get(k) for k in ("id", "type", "label", "required", "options", "value")})
        for r in raw
    ]


def fill_value(scope, f: Field, value: str, h: Humanizer) -> bool:
    loc = scope.locator(f'[data-jam="{f.id}"]')
    if f.type in TEXTLIKE:
        h.type_into(loc, value)
    elif f.type == "select":
        opt = match_option(value, f.options)
        if opt is None:
            return False
        loc.select_option(label=opt)
    elif f.type == "radio":
        opt = match_option(value, f.options)
        if opt is None:
            return False
        scope.locator(f'[data-jam="{f.id}_{f.options.index(opt)}"]').check(force=True)
    elif f.type == "checkbox":
        if value.strip().lower() in ("yes", "true", "y", "1"):
            loc.check(force=True)
    else:
        return False
    h.pause(0.2, 0.6)
    return True


def is_resume_input(f: Field) -> bool:
    return f.type == "file" and (
        not f.label or any(k in f.label.lower() for k in ("resume", "cv", "curriculum", "upload"))
    )


def fill_form(
    scope,
    resolver: QuestionResolver,
    resume_path: str | None,
    h: Humanizer,
    root: str = "body",
    fields: list[Field] | None = None,
) -> FillReport:
    """Fill every visible field we can answer from resume/answer-bank data. Pre-filled values
    are kept. Required fields with no known answer are returned in `unknown` -- never guessed."""
    rep = FillReport()
    for f in fields if fields is not None else extract_fields(scope, root):
        if f.type == "password":
            rep.skipped.append(f.label)
            continue
        if f.type == "file":
            if is_resume_input(f) and resume_path:
                scope.locator(f'[data-jam="{f.id}"]').set_input_files(resume_path)
                rep.filled[f.label or "resume"] = "<resume file>"
            elif f.required:
                rep.unknown.append(f)
            continue
        if f.value and f.type != "checkbox":
            continue  # keep prefilled values
        if f.type == "checkbox" and f.value:
            continue
        ans = resolver.resolve(f.label, f.options or None) if f.label else None
        if ans is not None and fill_value(scope, f, ans, h):
            rep.filled[f.label] = ans
        elif f.required:
            rep.unknown.append(f)
        else:
            rep.skipped.append(f.label)
    return rep
