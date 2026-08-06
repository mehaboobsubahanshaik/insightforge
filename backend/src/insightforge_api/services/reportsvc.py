"""Dashboard -> PDF renderer, shared by the export endpoint and scheduled
reports so both produce identical governed numbers, always with the trust
line (freshness, quality score, quarantine note)."""

from fpdf import FPDF

_TRANSLIT = {"\u2014": "-", "\u2013": "-", "\u2019": "'", "\u2018": "'",
             "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u00d7": "x",
             "\u2192": "->", "\u2022": "*"}


def _pdf_text(value) -> str:
    """fpdf core fonts are latin-1; transliterate common punctuation and
    replace anything else so exotic dataset values can never 500 a report."""
    s = str(value)
    for k, v in _TRANSLIT.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def safe_filename(name: str, ext: str) -> str:
    """HTTP headers are latin-1; keep download filenames plain ASCII."""
    cleaned = _pdf_text(name)
    cleaned = "".join(c if c.isalnum() or c in " ._-" else "_" for c in cleaned)
    cleaned = cleaned.strip() or "export"
    return f"{cleaned[:40]}.{ext}"


def render_dashboard_pdf(data: dict) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, _pdf_text(data["name"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    trust = (f"Data freshness: {data.get('freshness') or 'n/a'}  |  Quality score: "
             f"{data.get('quality_score')}  |  Quarantined rows excluded")
    pdf.cell(0, 7, _pdf_text(trust), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    for w in data["widgets"]:
        if w.get("error"):
            continue
        if "value" in w:
            pdf.set_font("Helvetica", "B", 12)
            value = w.get("value")
            label = f"{w['title']}: {value:,.2f}" if value is not None else f"{w['title']}: -"
            pdf.cell(0, 8, _pdf_text(label), new_x="LMARGIN", new_y="NEXT")
        elif w.get("groups"):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, _pdf_text(w["title"]), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10)
            for g in w["groups"][:20]:
                pdf.cell(90, 6, _pdf_text(g["group"])[:40])
                pdf.cell(0, 6, f"{g['value']:,.2f}", new_x="LMARGIN", new_y="NEXT")
        elif w.get("pivot"):
            pv = w["pivot"]
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, _pdf_text(w["title"]), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 8)
            pdf.cell(45, 6, "")
            for ck in pv["cols"][:6]:
                pdf.cell(24, 6, _pdf_text(ck)[:12])
            pdf.ln()
            for i, rk in enumerate(pv["rows"][:15]):
                pdf.cell(45, 6, _pdf_text(rk)[:24])
                for j in range(min(len(pv["cols"]), 6)):
                    cell = pv["cells"][i][j]
                    pdf.cell(24, 6, f"{cell:,.0f}" if cell is not None else "-")
                pdf.ln()
    return bytes(pdf.output())


def neutralize_csv_cell(value) -> str:
    """Formula-injection protection for CSV exports."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s
