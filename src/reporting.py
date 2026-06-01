"""
KYB Intelligence Pipeline — PDF Report Generation
====================================================
Phase 6 dari KYB Pipeline:
1. Baca KYBInvestigationOutput (final_summary.json) + data HCAT
2. Baca HTML template dari templates/report_template.html
3. Inject data JSON ke HTML menggunakan Jinja2
4. Render HTML → PDF menggunakan pdfkit (wkhtmltopdf)
"""

import json
import os
from pathlib import Path

import jinja2
import pdfkit

from src.config import TEMPLATE_DIR, SUMMARY_DIR


# ─── Jinja2 Environment ──────────────────────────────────────────────────────

_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=jinja2.select_autoescape(["html"]),
)


# ─── pdfkit Options ──────────────────────────────────────────────────────────

_pdfkit_config = None
_wk_path = r"C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe"
_wk_path_x86 = r"C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe"
if os.path.exists(_wk_path):
    _pdfkit_config = pdfkit.configuration(wkhtmltopdf=_wk_path)
elif os.path.exists(_wk_path_x86):
    _pdfkit_config = pdfkit.configuration(wkhtmltopdf=_wk_path_x86)

PDFKIT_OPTIONS = {
    "page-size": "A4",
    "margin-top": "10mm",
    "margin-right": "10mm",
    "margin-bottom": "10mm",
    "margin-left": "10mm",
    "encoding": "UTF-8",
    "enable-local-file-access": "",
    "print-media-type": "",
    "no-outline": "",
    "dpi": 300,
}


# ─── JSON Output ─────────────────────────────────────────────────────────────

def save_json(kyb_output_dict: dict, output_dir: str = None) -> str:
    """
    Simpan KYBInvestigationOutput sebagai JSON ke summary/json/.

    Args:
        kyb_output_dict: dict dari KYBInvestigationOutput.model_dump()
        output_dir: Override output directory (default: summary/json/)

    Returns:
        Path ke file JSON yang disimpan
    """
    out = Path(output_dir) if output_dir else SUMMARY_DIR / "json"
    out.mkdir(parents=True, exist_ok=True)

    name = kyb_output_dict.get("corporate_entity", {}).get("name", "UNKNOWN")
    safe = name.replace(" ", "_").replace("/", "-")
    filepath = out / f"{safe}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(kyb_output_dict, f, indent=2, ensure_ascii=False)

    print(f"   💾 JSON tersimpan : {filepath}")
    return str(filepath)


# ─── PDF Output ──────────────────────────────────────────────────────────────

def generate_pdf(kyb_output_dict: dict,
                 hcat_result: dict = None,
                 output_dir: str = None) -> str:
    """
    Generate PDF report dari KYBInvestigationOutput + HCAT metadata.

    Framework: "Gunakan Jinja2 untuk menginjeksi data JSON ke dalam HTML.
    Gunakan pustaka pdfkit (dengan wkhtmltopdf) untuk me-render HTML
    menjadi laporan PDF final."

    Args:
        kyb_output_dict: dict dari KYBInvestigationOutput.model_dump()
        hcat_result: dict hasil HCAT evaluation (opsional)
        output_dir: Override output directory

    Returns:
        Path ke file PDF yang dihasilkan
    """
    out = Path(output_dir) if output_dir else SUMMARY_DIR / "pdf"
    out.mkdir(parents=True, exist_ok=True)

    name = kyb_output_dict.get("corporate_entity", {}).get("name", "UNKNOWN")
    safe = name.replace(" ", "_").replace("/", "-")
    filepath = out / f"{safe}.pdf"

    # Prepare template context
    context = dict(kyb_output_dict)

    # Embed HCAT confidence jika tersedia
    if hcat_result:
        context["hcat_confidence"] = hcat_result.get("hcat_confidence_pct", None)
    else:
        context["hcat_confidence"] = None

    # Render HTML
    try:
        template = _jinja_env.get_template("report_template.html")
    except jinja2.TemplateNotFound:
        print(f"   ⚠️ Template tidak ditemukan di {TEMPLATE_DIR}")
        print("   ⚠️ Membuat PDF dengan template fallback...")
        return _generate_fallback_pdf(kyb_output_dict, filepath)

    html_content = template.render(**context)

    # Save intermediate HTML (untuk debugging)
    html_path = out / f"{safe}.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # Render PDF via pdfkit
    try:
        if _pdfkit_config:
            pdfkit.from_string(html_content, str(filepath), options=PDFKIT_OPTIONS, configuration=_pdfkit_config)
        else:
            pdfkit.from_string(html_content, str(filepath), options=PDFKIT_OPTIONS)
        print(f"   📄 PDF tersimpan  : {filepath}")
    except OSError as e:
        if "wkhtmltopdf" in str(e).lower() or "No wkhtmltopdf" in str(e):
            print(f"\n   ⚠️ wkhtmltopdf tidak ditemukan!")
            print(f"   📥 Install dari: https://wkhtmltopdf.org/downloads.html")
            print(f"   📄 HTML tersimpan : {html_path} (bisa dibuka di browser)")
        else:
            print(f"   ⚠️ PDF generation error: {e}")
            print(f"   📄 HTML tersimpan : {html_path}")

    return str(filepath)


# ─── Fallback PDF (tanpa template) ──────────────────────────────────────────

def _generate_fallback_pdf(kyb_output_dict: dict, filepath: Path) -> str:
    """Generate PDF minimal jika template HTML tidak tersedia."""
    name = kyb_output_dict.get("corporate_entity", {}).get("name", "?")
    score = kyb_output_dict.get("ai_risk_scoring", {}).get("risk_contamination_score", 0)
    level = kyb_output_dict.get("ai_risk_scoring", {}).get("overall_risk_level", "?")
    action = kyb_output_dict.get("ai_recommendation", {}).get("action", "?")

    html = f"""
    <html><head><meta charset="utf-8"><title>KYB Report - {name}</title>
    <style>body {{ font-family: Arial; padding: 40px; }}</style></head>
    <body>
    <h1>KYB Intelligence Report</h1>
    <h2>{name}</h2>
    <p><strong>Risk Score:</strong> {score}/100</p>
    <p><strong>Risk Level:</strong> {level}</p>
    <p><strong>Recommendation:</strong> {action}</p>
    <hr>
    <pre>{json.dumps(kyb_output_dict, indent=2, ensure_ascii=False)[:5000]}</pre>
    </body></html>
    """

    try:
        if _pdfkit_config:
            pdfkit.from_string(html, str(filepath), options=PDFKIT_OPTIONS, configuration=_pdfkit_config)
        else:
            pdfkit.from_string(html, str(filepath), options=PDFKIT_OPTIONS)
        print(f"   📄 PDF (fallback) : {filepath}")
    except Exception:
        with open(str(filepath).replace(".pdf", ".html"), "w", encoding="utf-8") as f:
            f.write(html)
        print(f"   📄 HTML fallback  : {filepath}")

    return str(filepath)
