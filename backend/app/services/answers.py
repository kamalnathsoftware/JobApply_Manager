"""Answers screening/form questions from (1) the parsed resume, then (2) the user's answer
bank. Anything else returns None -> the caller must stop and ask a human; we never guess."""

import re
from dataclasses import dataclass, field

# Suggested entries the UI offers to create (user fills in the answer).
DEFAULT_BANK = [
    (
        "expected_ctc",
        "Expected salary / CTC",
        ["expected ctc", "expected salary", "salary expectation", "expected compensation"],
    ),
    (
        "current_ctc",
        "Current salary / CTC",
        ["current ctc", "current salary", "current compensation"],
    ),
    (
        "notice_period",
        "Notice period",
        ["notice period", "how soon can you join", "earliest joining", "joining time"],
    ),
    ("relocation", "Willing to relocate", ["relocate", "relocation"]),
    (
        "work_auth",
        "Authorized to work",
        [
            "authorized to work",
            "authorised to work",
            "legally authorized",
            "work permit",
            "right to work",
        ],
    ),
    ("sponsorship", "Requires visa sponsorship", ["sponsorship", "require visa"]),
    (
        "remote",
        "Comfortable with remote/hybrid/onsite",
        ["remote", "hybrid", "on-site", "onsite", "work from office"],
    ),
]

_YES = {"yes", "y", "true", "1"}
_NO = {"no", "n", "false", "0"}


def normalize(q: str) -> str:
    q = re.sub(r"[^a-z0-9+#. ]+", " ", q.lower())
    return re.sub(r"\s+", " ", q).strip()


def match_option(answer: str, options: list[str]) -> str | None:
    """Pick the option that best corresponds to `answer`, or None."""
    a = normalize(answer)
    if not a or not options:
        return None
    norm = [(o, normalize(o)) for o in options]
    for o, n in norm:
        if n == a:
            return o
    if a in _YES or a in _NO:
        want = _YES if a in _YES else _NO
        for o, n in norm:
            if n.split(" ")[0] in want:
                return o
    for o, n in norm:
        if n and (a in n.split() or n in a.split()):
            return o
    for o, n in norm:
        if n and (a in n or n in a):
            return o
    return None


@dataclass
class BankEntry:
    patterns: list[str]
    answer: str
    sensitive: bool = False  # never included in prompts sent to an LLM provider


@dataclass
class QuestionResolver:
    profile: dict = field(default_factory=dict)  # ParsedResume.model_dump()
    bank: list[BankEntry] = field(default_factory=list)

    # ---- resume-derived answers -------------------------------------------------
    def _from_resume(self, q: str) -> str | None:
        c = (self.profile or {}).get("contact") or {}
        p = self.profile or {}
        name = c.get("name") or ""
        parts = name.split()
        if re.search(r"\b(e ?mail)\b", q):
            return c.get("email")
        if re.search(r"\b(phone|mobile|contact number|telephone)\b", q):
            return re.sub(r"[^\d+]", "", c.get("phone") or "") or None
        if re.search(r"\bfirst name\b", q):
            return parts[0] if parts else None
        if re.search(r"\b(last name|surname|family name)\b", q):
            return parts[-1] if len(parts) > 1 else None
        if re.search(r"\b(full name|your name|^name)\b", q) or q == "name":
            return name or None
        if "linkedin" in q:
            return c.get("linkedin")
        if "github" in q:
            return c.get("github")
        if re.search(r"\b(website|portfolio)\b", q):
            return c.get("website")
        if re.search(r"\b(current )?(city|location)\b|where are you (based|located)", q):
            return c.get("location")
        if re.search(r"current (company|employer)|present employer", q):
            return p.get("current_company")
        if re.search(r"current (title|designation|role)|job title", q):
            return p.get("current_title")
        m = re.search(
            r"years of (?:total |overall |relevant |professional |work )?experience(.*)", q
        )
        skill_specific = m and re.search(
            r"\b(in|with|using|on|of|for)\s+(?!total\b|overall\b|all\b|years\b)\w+", m.group(1)
        )
        if (m and not skill_specific) or re.search(r"\b(total|overall) experience\b", q):
            y = p.get("total_experience_years")
            if y is not None:
                return str(int(y)) if float(y).is_integer() else f"{y:.1f}"
        return None

    # ---- main entry ---------------------------------------------------------------
    def resolve(self, question: str, options: list[str] | None = None) -> str | None:
        q = normalize(question)
        if not q:
            return None
        candidates: list[str] = []
        for e in self.bank:
            if any(p and normalize(p) in q for p in e.patterns):
                candidates.append(e.answer)
        r = self._from_resume(q)
        if r:
            candidates.append(r)
        for ans in candidates:
            if options:
                m = match_option(ans, options)
                if m is not None:
                    return m
            else:
                return ans
        return None
