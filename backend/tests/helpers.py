import io

import docx


def make_pdf(text_lines: list[str]) -> bytes:
    """Minimal single-page PDF with real extractable text (no extra dependencies)."""
    content = "BT /F1 12 Tf 50 750 Td 14 TL\n"
    for line in text_lines:
        esc = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content += f"({esc}) Tj T*\n"
    content += "ET"
    objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def make_docx(paragraphs: list[str]) -> bytes:
    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


class FakeLLM:
    """Returns canned JSON; records prompts. `responses` may be a dict or a callable."""

    model = "fake-model"

    def __init__(self, responses=None):
        self.responses = responses if responses is not None else {}
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, max_tokens: int = 8000):
        self.calls.append((system, user))
        r = self.responses
        if isinstance(r, Exception):
            raise r
        return r(system, user) if callable(r) else r
