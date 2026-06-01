import json
import os
from datetime import datetime
from fpdf import FPDF
from src.core.state import CompanyProfileOutput


class CustomerProfilingReport(FPDF):
    """PDF Report Generator untuk Customer Profiling."""

    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "CONFIDENTIAL - Customer Profiling Report", align="C", new_x="LMARGIN", new_y="NEXT")
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Halaman {self.page_no()}/{{nb}} | Generated: {datetime.now().strftime('%d-%m-%Y %H:%M')}", align="C")

    def _section_title(self, title: str):
        self.ln(3)
        self.set_fill_color(41, 65, 122)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 11)
        self.cell(0, 9, f"  {title}", fill=True, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(2)

    def _subsection_title(self, title: str):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(41, 65, 122)
        self.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def _key_value_row(self, key: str, value: str, key_width: int = 60):
        self.set_font("Helvetica", "B", 9)
        self.cell(key_width, 6, key, new_x="RIGHT")
        self.set_font("Helvetica", "", 9)
        self.multi_cell(0, 6, f": {value}", new_x="LMARGIN", new_y="NEXT")

    def _risk_badge(self, classification: str, score: int):
        """Render risk badge berwarna."""
        colors = {
            "Low Risk": (46, 125, 50),
            "Moderate Risk": (245, 166, 35),
            "Moderate-High Risk": (230, 126, 34),
            "High Risk": (211, 47, 47),
        }
        color = colors.get(classification, (128, 128, 128))

        self.ln(3)
        self.set_fill_color(*color)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 14)
        badge_text = f"  {classification.upper()}  |  Score: {score}/100  "
        self.cell(0, 12, badge_text, fill=True, align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(3)

    def _internet_risk_badge(self, risk_level: str):
        """Render badge risiko internet."""
        colors = {
            "Clean": (46, 125, 50),
            "Flag for Review": (245, 166, 35),
            "High Risk": (211, 47, 47),
        }
        color = colors.get(risk_level, (128, 128, 128))

        self.set_fill_color(*color)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 10)
        self.cell(0, 8, f"  Internet Risk: {risk_level.upper()}  ", fill=True, align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(2)


class ReportGenerator:
    """Generates PDF and JSON output files from the completed company profile."""

    @staticmethod
    def save_json(profile: CompanyProfileOutput, output_dir: str = "output") -> str:
        """Simpan profil sebagai file JSON."""
        os.makedirs(output_dir, exist_ok=True)
        company_name = profile.company.name or "UNKNOWN"
        filename = f"{company_name}.json"
        filepath = os.path.join(output_dir, filename)

        # Output JSON tanpa risk_assessment (sesuai format contoh)
        output_data = profile.model_dump()
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False)

        print(f"   💾 JSON tersimpan: {filepath}")
        return filepath

    @staticmethod
    def generate_pdf(profile: CompanyProfileOutput, output_dir: str = "output") -> str:
        """Generate PDF report dari profil perusahaan."""
        os.makedirs(output_dir, exist_ok=True)
        company_name = profile.company.name or "UNKNOWN"
        filename = f"{company_name}.pdf"
        filepath = os.path.join(output_dir, filename)

        pdf = CustomerProfilingReport()
        pdf.alias_nb_pages()
        pdf.add_page()

        # ============ COVER / TITLE ============
        pdf.set_font("Helvetica", "B", 20)
        pdf.set_text_color(41, 65, 122)
        pdf.ln(10)
        pdf.cell(0, 12, "CUSTOMER PROFILING REPORT", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 12)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 8, "AI-KYB Autonomous Intelligence System", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(0, 0, 0)
        pdf.cell(0, 10, company_name, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

        # Risk Badge
        risk = profile.risk_assessment
        pdf._risk_badge(risk.risk_classification, risk.overall_risk_score)

        # ============ 1. INFORMASI PERUSAHAAN ============
        pdf._section_title("1. INFORMASI PERUSAHAAN")
        c = profile.company
        pdf._key_value_row("Nama Perusahaan", c.name)
        pdf._key_value_row("SK Pengesahan", f"{c.skNumber} ({c.skDate})")
        pdf._key_value_row("SP Perusahaan", f"{c.companySpNumber} ({c.companySpDate})")
        pdf._key_value_row("Jenis", c.type)
        pdf._key_value_row("Jangka Waktu", c.timePeriod)
        pdf._key_value_row("Status", c.status)
        pdf._key_value_row("Jenis Transaksi", c.transactionType)

        # ============ 2. ALAMAT ============
        pdf._section_title("2. ALAMAT PERUSAHAAN")
        addr = profile.companyAddress
        full_addr = f"{addr.address}, {addr.ward}, {addr.subdistrict}, {addr.regency}, {addr.province} {addr.postalCode}"
        pdf._key_value_row("Alamat Lengkap", full_addr)

        # ============ 3. NOTARIS ============
        pdf._section_title("3. INFORMASI NOTARIS")
        n = profile.notary
        pdf._key_value_row("Notaris", n.name)
        pdf._key_value_row("Alamat Notaris", n.shortAddress)
        pdf._key_value_row("Nomor Akta", f"{n.deedNumber} ({n.deedDate})")

        # ============ 4. STRUKTUR MODAL ============
        pdf._section_title("4. STRUKTUR MODAL")
        pdf._subsection_title("Modal Dasar")
        pdf._key_value_row("Jumlah Saham", profile.baseStock.numberOfShares)
        pdf._key_value_row("Nilai Total", profile.baseStock.grandTotal)
        pdf._subsection_title("Modal Ditempatkan")
        pdf._key_value_row("Jumlah Saham", profile.issuedStock.numberOfShares)
        pdf._key_value_row("Nilai Total", profile.issuedStock.grandTotal)
        pdf._key_value_row("Modal Disetor", profile.paidUpStock)

        # ============ 5. PEMEGANG SAHAM ============
        pdf._section_title("5. PEMEGANG SAHAM & PENGURUS")
        pdf.set_font("Helvetica", "B", 8)

        # Table header
        col_widths = [8, 45, 30, 30, 25, 25, 27]
        headers = ["No", "Nama", "Jabatan", "Alamat", "Jml Saham", "Nilai", "% Saham"]
        pdf.set_fill_color(220, 230, 241)
        for i, header in enumerate(headers):
            pdf.cell(col_widths[i], 7, header, border=1, fill=True, align="C")
        pdf.ln()

        # Table rows - calculate total shares dynamically
        total_shares = 0
        try:
            total_shares = int(profile.paidUpStock.replace("Rp. ", "").replace(",", "").replace(".", "").strip())
        except (ValueError, AttributeError):
            total_shares = 500000000
        
        # If paidUpStock is in currency, use baseStock for share count
        if total_shares > 100000000000:  # likely a currency value not share count
            try:
                total_shares = int(profile.baseStock.numberOfShares)
            except (ValueError, AttributeError):
                total_shares = 500000000

        pdf.set_font("Helvetica", "", 7)
        for idx, sh in enumerate(profile.shareholders, 1):
            try:
                shares = int(sh.numberOfShares)
                pct = f"{(shares / total_shares * 100):.2f}%"
            except (ValueError, ZeroDivisionError):
                pct = "N/A"

            row_data = [
                str(idx), sh.name[:25], sh.position[:18],
                sh.address[:18], sh.numberOfShares[:15], sh.grandTotal[:15], pct
            ]
            for i, data in enumerate(row_data):
                pdf.cell(col_widths[i], 6, data, border=1, align="C" if i in [0, 6] else "L")
            pdf.ln()

        # ============ 6. KBLI ============
        pdf.add_page()
        pdf._section_title("6. MAKSUD DAN TUJUAN (KBLI)")
        pdf.set_font("Helvetica", "B", 8)
        kbli_cols = [8, 18, 50, 114]
        kbli_headers = ["No", "Kode", "Nama Kegiatan", "Deskripsi"]
        pdf.set_fill_color(220, 230, 241)
        for i, header in enumerate(kbli_headers):
            pdf.cell(kbli_cols[i], 7, header, border=1, fill=True, align="C")
        pdf.ln()

        pdf.set_font("Helvetica", "", 7)
        for goal in profile.companyGoals:
            x_start = pdf.get_x()
            y_start = pdf.get_y()
            
            # Calculate row height based on description length
            desc_text = goal.description[:200] if goal.description else "-"
            row_h = max(6, pdf.get_string_width(desc_text) / kbli_cols[3] * 4 + 4)
            row_h = min(row_h, 18)  # cap height
            
            pdf.cell(kbli_cols[0], row_h, str(goal.no), border=1, align="C")
            pdf.cell(kbli_cols[1], row_h, goal.code, border=1, align="C")
            pdf.cell(kbli_cols[2], row_h, goal.name[:30], border=1)
            
            # Multi-cell for description
            x_desc = pdf.get_x()
            pdf.multi_cell(kbli_cols[3], row_h, desc_text[:150], border=1)
            
            if pdf.get_y() - y_start < row_h:
                pdf.set_y(y_start + row_h)

        # ============ 7. RISK ASSESSMENT ============
        pdf.add_page()
        pdf._section_title("7. ANALISIS RISIKO")
        pdf._risk_badge(risk.risk_classification, risk.overall_risk_score)

        # UBO Analysis
        pdf._subsection_title("7.1 Ultimate Beneficial Owner (UBO) Analysis")
        if risk.ubo_analysis.identified_ubos:
            for ubo in risk.ubo_analysis.identified_ubos:
                name = getattr(ubo, "name", "Unknown")
                pct = getattr(ubo, "percentage", 0)
                pos = getattr(ubo, "position", "-")
                pdf._key_value_row(f"  {name}", f"{pct}% kepemilikan (Jabatan: {pos})")
        pdf._key_value_row("UBO >25%", "Ya" if risk.ubo_analysis.has_ubo_above_threshold else "Tidak")

        # Litigation Summary
        pdf._subsection_title("7.2 Ringkasan Litigasi (SIPP MA)")
        pdf._key_value_row("Total Kasus", str(risk.litigation_summary.total_cases))
        if risk.litigation_summary.cases:
            for case in risk.litigation_summary.cases:
                nomor = getattr(case, "nomor_perkara", "-")
                klasifikasi = getattr(case, "klasifikasi", "-")
                status = getattr(case, "status", "-")
                pdf._key_value_row(f"  Perkara {nomor}", f"{klasifikasi} | Status: {status}")

        # Key Findings
        pdf._subsection_title("7.3 Temuan Utama")
        pdf.set_font("Helvetica", "", 9)
        for i, finding in enumerate(risk.key_findings, 1):
            pdf.set_x(15)
            pdf.multi_cell(0, 5, f"{i}. {finding}", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)

        # Recommendation
        pdf._subsection_title("7.4 Rekomendasi Regulasi")
        pdf.set_font("Helvetica", "B", 11)
        rec_color = {
            "Setujui": (46, 125, 50),
            "Setujui dengan Monitoring": (245, 166, 35),
            "Enhanced Due Diligence (EDD) Required": (230, 126, 34),
            "Tolak / Eskalasi ke Komite": (211, 47, 47),
        }
        color = rec_color.get(risk.regulatory_recommendation, (0, 0, 0))
        pdf.set_text_color(*color)
        pdf.cell(0, 10, risk.regulatory_recommendation, align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

        # ============ 8. INTERNET RESEARCH FINDINGS (NEW) ============
        if profile.internet_research:
            pdf.add_page()
            pdf._section_title("8. HASIL RISET INTERNET (OSINT)")
            
            ir = profile.internet_research
            pdf._internet_risk_badge(ir.overall_internet_risk)

            # 8.1 Adverse Media
            pdf._subsection_title("8.1 Adverse Media Screening")
            if ir.adverse_media:
                for i, media in enumerate(ir.adverse_media, 1):
                    severity_color = {
                        "Low": (46, 125, 50),
                        "Medium": (245, 166, 35),
                        "High": (211, 47, 47)
                    }
                    sev_color = severity_color.get(media.severity, (128, 128, 128))
                    
                    pdf.set_font("Helvetica", "B", 9)
                    pdf.set_x(15)
                    pdf.cell(0, 6, f"{i}. [{media.severity.upper()}] {media.headline[:80]}", new_x="LMARGIN", new_y="NEXT")
                    pdf.set_font("Helvetica", "", 8)
                    pdf.set_x(20)
                    pdf.multi_cell(0, 5, f"Entitas: {media.entity_name} | Sumber: {media.source[:60]}", new_x="LMARGIN", new_y="NEXT")
                    pdf.set_x(20)
                    pdf.multi_cell(0, 5, f"Ringkasan: {media.summary[:200]}", new_x="LMARGIN", new_y="NEXT")
                    pdf.ln(2)
            else:
                pdf.set_font("Helvetica", "", 9)
                pdf.set_x(15)
                pdf.cell(0, 6, "Tidak ditemukan adverse media yang signifikan.", new_x="LMARGIN", new_y="NEXT")
                pdf.ln(2)

            # 8.2 Sanctions Screening
            pdf._subsection_title("8.2 Sanctions List Screening")
            if ir.sanctions_screening:
                for screening in ir.sanctions_screening:
                    status_text = "TERDETEKSI" if screening.is_sanctioned else "BERSIH"
                    if screening.is_sanctioned:
                        pdf.set_text_color(211, 47, 47)
                    else:
                        pdf.set_text_color(46, 125, 50)
                    
                    pdf.set_font("Helvetica", "B", 9)
                    pdf.set_x(15)
                    pdf.cell(0, 6, f"{screening.entity_name}: {status_text}", new_x="LMARGIN", new_y="NEXT")
                    pdf.set_text_color(0, 0, 0)
                    
                    if screening.screening_notes:
                        pdf.set_font("Helvetica", "", 8)
                        pdf.set_x(20)
                        pdf.multi_cell(0, 5, f"Catatan: {screening.screening_notes[:200]}", new_x="LMARGIN", new_y="NEXT")
                    pdf.ln(1)
            else:
                pdf.set_font("Helvetica", "", 9)
                pdf.set_x(15)
                pdf.cell(0, 6, "Tidak ada data sanctions screening.", new_x="LMARGIN", new_y="NEXT")
                pdf.ln(2)

            # 8.3 PEP Detection
            pdf._subsection_title("8.3 Politically Exposed Person (PEP) Detection")
            if ir.pep_flags:
                for pep in ir.pep_flags:
                    status_text = "TERDETEKSI PEP" if pep.is_pep else "Bukan PEP"
                    if pep.is_pep:
                        pdf.set_text_color(230, 126, 34)
                    else:
                        pdf.set_text_color(46, 125, 50)
                    
                    pdf.set_font("Helvetica", "B", 9)
                    pdf.set_x(15)
                    pdf.cell(0, 6, f"{pep.name}: {status_text}", new_x="LMARGIN", new_y="NEXT")
                    pdf.set_text_color(0, 0, 0)
                    
                    if pep.is_pep and pep.details:
                        pdf.set_font("Helvetica", "", 8)
                        pdf.set_x(20)
                        pdf.multi_cell(0, 5, f"Kategori: {pep.pep_category} | Detail: {pep.details[:200]}", new_x="LMARGIN", new_y="NEXT")
                    pdf.ln(1)
            else:
                pdf.set_font("Helvetica", "", 9)
                pdf.set_x(15)
                pdf.cell(0, 6, "Tidak ada PEP terdeteksi di antara pemegang saham.", new_x="LMARGIN", new_y="NEXT")
                pdf.ln(2)

            # 8.4 Business Legitimacy
            if ir.business_legitimacy_notes:
                pdf._subsection_title("8.4 Verifikasi Legitimasi Bisnis")
                pdf.set_font("Helvetica", "", 9)
                pdf.set_x(15)
                pdf.multi_cell(0, 5, ir.business_legitimacy_notes[:500], new_x="LMARGIN", new_y="NEXT")

        # Save
        pdf.output(filepath)
        print(f"   📄 PDF tersimpan: {filepath}")
        return filepath
