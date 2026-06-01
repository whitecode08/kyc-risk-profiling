import json
import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
from src.agents.graph import AgenticWorkflow
from src.validation.hcat_tester import HCATStatisticalTester
from src.core.state import PipelineState, InputMode
from src.tools.ahu_scraper import AHUScraperTool
from src.tools.sipp_scraper import SIPPScraperTool
from src.tools.ppatk_tool import PPATKTool


def print_banner():
    print("╔" + "═" * 58 + "╗")
    print("║" + " AI-KYB CUSTOMER PROFILING SYSTEM ".center(58) + "║")
    print("║" + " Autonomous Intelligence Pipeline v2.0 ".center(58) + "║")
    print("║" + " (with Internet Research & NIB Lookup) ".center(58) + "║")
    print("╚" + "═" * 58 + "╝")


def choose_input_mode() -> str:
    """Tampilkan menu pilihan mode input."""
    print("\n📋 PILIH MODE INPUT DATA:")
    print("─" * 40)
    print("  [1] NIB + Nama Perusahaan (Auto-Lookup)")
    print("      → Cari data AHU & SIPP otomatis dari internal DB")
    print()
    print("  [2] Upload Manual (PDF/JSON/CSV)")
    print("      → Input file AHU (PDF/JSON/CSV) dan SIPP/PPATK (JSON/CSV)")
    print("─" * 40)
    
    while True:
        choice = input("\n🔹 Pilih mode (1/2): ").strip()
        if choice in ["1", "2"]:
            return choice
        print("   ⚠️ Input tidak valid. Masukkan 1 atau 2.")


def input_nib_mode() -> tuple:
    """Input NIB dan Nama Perusahaan."""
    print("\n🔐 MODE 1: NIB + NAMA PERUSAHAAN")
    print("─" * 40)
    
    # Tampilkan NIB yang tersedia (untuk demo)
    available = AHUScraperTool.get_available_nibs()
    if available:
        print("   📋 NIB tersedia dalam database (untuk demo):")
        for nib, company in available.items():
            print(f"      • {nib} → {company}")
        print()
    
    nib = input("   NIB (Nomor Induk Berusaha): ").strip()
    company_name = input("   Nama Perusahaan: ").strip()
    
    if not company_name:
        print("   ⚠️ Nama perusahaan wajib diisi!")
        sys.exit(1)
    
    return nib, company_name


def input_upload_mode() -> PipelineState:
    """Input file upload manual (PDF/JSON/CSV)."""
    print("\n📄 MODE 2: UPLOAD MANUAL")
    print("─" * 40)

    company_name = input("   Nama Perusahaan: ").strip()
    if not company_name:
        print("   ⚠️ Nama perusahaan wajib diisi!")
        sys.exit(1)

    state = PipelineState(
        company_name=company_name,
        input_mode=InputMode.MANUAL_UPLOAD
    )

    # ============ AHU Data ============
    print("\n   📋 DATA AHU (Profil Perusahaan):")
    print("      [1] Upload file JSON")
    print("      [2] Upload file CSV")
    print("      [3] Upload file PDF")
    print("      [4] Skip (tidak ada data AHU)")

    ahu_choice = input("      Pilih (1/2/3/4): ").strip()

    if ahu_choice == "1":
        path = input("      Path file JSON AHU: ").strip().strip('"')
        state.raw_ahu_data = AHUScraperTool.load_from_json(path)
    elif ahu_choice == "2":
        path = input("      Path file CSV AHU: ").strip().strip('"')
        result = AHUScraperTool.load_from_csv(path)
        if "error" not in result:
            # Setelah import CSV, coba lookup company_name dari DB
            state.raw_ahu_data = AHUScraperTool.get_company_profile(company_name)
        else:
            state.raw_ahu_data = result
    elif ahu_choice == "3":
        path = input("      Path file PDF AHU: ").strip().strip('"')
        print("      ⏳ Mengekstrak data dari PDF menggunakan AI...")
        state.raw_ahu_data = AHUScraperTool.extract_from_pdf(path)
    else:
        state.raw_ahu_data = {"error": "Data AHU tidak tersedia (skipped)"}

    # ============ SIPP Data ============
    print("\n   📋 DATA SIPP (Riwayat Litigasi):")
    print("      [1] Upload file JSON")
    print("      [2] Skip (gunakan data dari DB scraping)")

    sipp_choice = input("      Pilih (1/2): ").strip()

    if sipp_choice == "1":
        path = input("      Path file JSON SIPP: ").strip().strip('"')
        state.raw_sipp_data = SIPPScraperTool.load_from_json(path)

    # ============ PPATK Data ============
    print("\n   📋 DATA PPATK DTTOT (Daftar Sanksi Keuangan Terarah):")
    print("      [1] Upload file JSON (format DTTOT)")
    print("      [2] Upload file CSV")
    print("      [3] Skip (gunakan data dari DB / tidak ada)")

    ppatk_choice = input("      Pilih (1/2/3): ").strip()

    if ppatk_choice == "1":
        path = input("      Path file JSON PPATK: ").strip().strip('"')
        count = PPATKTool.load_from_json(path)
        print(f"      ✅ {count} entri PPATK diimport ke DB. Akan otomatis dicek saat profiling.")
    elif ppatk_choice == "2":
        path = input("      Path file CSV PPATK: ").strip().strip('"')
        count = PPATKTool.load_from_csv(path)
        print(f"      ✅ {count} entri PPATK diimport ke DB. Akan otomatis dicek saat profiling.")

    return state


def run_pipeline(state: PipelineState = None, company_name: str = None, nib: str = None):
    """Jalankan pipeline profiling."""
    
    # =========================================================
    # FASE 1-3: Agentic Workflow (Real-time Pipeline)
    # =========================================================
    workflow = AgenticWorkflow(max_revisions=3)
    
    if state:
        final_state = workflow.run(
            company_name=state.company_name,
            state=state
        )
    else:
        final_state = workflow.run(
            company_name=company_name,
            nib=nib
        )

    if not final_state.company_profile:
        print("\n❌ Pipeline gagal: Profil perusahaan tidak berhasil dibuat.")
        return None

    # Tampilkan ringkasan output
    print("\n" + "=" * 60)
    print("📑 RINGKASAN OUTPUT")
    print("=" * 60)
    profile = final_state.company_profile
    risk = profile.risk_assessment

    print(f"   Perusahaan     : {profile.company.name}")
    print(f"   Pemegang Saham : {len(profile.shareholders)} orang/entitas")
    print(f"   KBLI           : {len(profile.companyGoals)} kegiatan usaha")
    print(f"   Risk Score     : {risk.overall_risk_score}/100")
    print(f"   Risk Level     : {risk.risk_classification}")
    print(f"   Rekomendasi    : {risk.regulatory_recommendation}")
    print(f"   Litigasi       : {risk.litigation_summary.total_cases} kasus")
    print(f"   UBO >25%       : {'Ya' if risk.ubo_analysis.has_ubo_above_threshold else 'Tidak'}")

    # PPATK Summary
    if final_state.raw_ppatk_data:
        pd = final_state.raw_ppatk_data
        ppatk_status = "🚨 ADA HIT SANKSI" if pd.get("has_active_sanctions") else (
            f"⚠️ {pd.get('total_hits',0)} hit (tidak aktif)" if pd.get("total_hits", 0) > 0
            else "✅ Bersih"
        )
        print(f"   PPATK DTTOT    : {ppatk_status} ({pd.get('total_checked',0)} entitas diperiksa)")

    # Internet Research Summary
    if final_state.internet_research:
        ir = final_state.internet_research
        print(f"   Internet Risk  : {ir.overall_internet_risk}")
        print(f"   Adverse Media  : {len(ir.adverse_media)} temuan")
        print(f"   Sanctions      : {'TERDETEKSI' if any(s.is_sanctioned for s in ir.sanctions_screening) else 'Bersih'}")
        print(f"   PEP            : {'TERDETEKSI' if any(p.is_pep for p in ir.pep_flags) else 'Tidak ada'}")
    
    print(f"   JSON Output    : {final_state.json_output_path}")
    print(f"   PDF Report     : {final_state.pdf_output_path}")

    # =========================================================
    # FASE 4: HCAT Shadow Evaluation (Asynchronous Validation)
    # =========================================================
    raw_contexts = [
        json.dumps(final_state.raw_ahu_data, ensure_ascii=False),
        json.dumps(final_state.raw_sipp_data, ensure_ascii=False)
    ]

    # Tambahkan PPATK ke context jika ada
    if final_state.raw_ppatk_data:
        raw_contexts.append(
            json.dumps(final_state.raw_ppatk_data, ensure_ascii=False)
        )

    # Tambahkan internet research ke context jika ada
    if final_state.internet_research:
        raw_contexts.append(
            json.dumps(final_state.internet_research.model_dump(), ensure_ascii=False)
        )

    tester = HCATStatisticalTester()
    hcat_result = tester.run_shadow_evaluation(
        raw_contexts,
        final_state.company_profile.model_dump()
    )

    # =========================================================
    # FINAL SUMMARY
    # =========================================================
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║" + " PIPELINE SELESAI ".center(58) + "║")
    print("╚" + "═" * 58 + "╝")
    print(f"   ✅ JSON Database : {final_state.json_output_path}")
    print(f"   ✅ PDF Report    : {final_state.pdf_output_path}")
    print(f"   ✅ HCAT Eval     : validation_reports/")
    print(f"   ✅ Risk Level    : {risk.risk_classification} ({risk.overall_risk_score}/100)")
    
    return final_state


def main():
    print_banner()
    
    mode = choose_input_mode()
    
    if mode == "1":
        # Mode NIB Lookup
        nib, company_name = input_nib_mode()
        print(f"\n🎯 Target: {company_name}" + (f" (NIB: {nib})" if nib else ""))
        print(f"{'─' * 60}")
        run_pipeline(company_name=company_name, nib=nib if nib else None)
    
    elif mode == "2":
        # Mode Manual Upload
        state = input_upload_mode()
        print(f"\n🎯 Target: {state.company_name} (Upload Manual)")
        print(f"{'─' * 60}")
        run_pipeline(state=state)


if __name__ == "__main__":
    main()