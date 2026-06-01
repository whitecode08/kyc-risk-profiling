"""
AI-KYB Intelligence Pipeline — Main Execution Script
======================================================
6-Phase Pipeline sesuai KYB Python Implementation Framework:

  Phase 1: Data Ingestion & Configuration
  Phase 2: SIPP Scraping & Structuring
  Phase 3: Internet Checking (OSINT) — Corporate & UBO
  Phase 4: Agentic Fusion & Risk Scoring
  Phase 5: HCAT Evaluation (Validation)
  Phase 6: PDF Generation

Usage:
  python run_pipeline.py --json data/input/ahu/01__aneka_bintang_gading.json
  python run_pipeline.py --company "ANEKA BINTANG GADING" --nib 1234567890
  python run_pipeline.py --interactive
  python run_pipeline.py  (default: interactive menu)
"""

import argparse
import json
import sys
import os
import time

sys.stdout.reconfigure(encoding="utf-8")

from src.data_ingestion import (
    load_ahu_json, find_ahu_by_name, scan_ahu_folder,
    extract_top5_ubo, get_company_metadata,
    load_all_ppatk, screen_ppatk,
)
from src.scrapers.sipp_scraper import run_sipp_scraping
from src.scrapers.osint_researcher import run_osint_research
from src.agents.fusion_agent import run_fusion, KYBInvestigationOutput
from src.agents.hcat_evaluator import HCATEvaluator
from src.reporting import save_json, generate_pdf


# ═══════════════════════════════════════════════════════════════════════════════
# Banner
# ═══════════════════════════════════════════════════════════════════════════════

def print_banner():
    print()
    print("╔" + "═" * 62 + "╗")
    print("║" + "  AI-KYB INTELLIGENCE SYSTEM  ".center(62) + "║")
    print("║" + "  Know Your Business — Autonomous Risk Profiling v3.0  ".center(62) + "║")
    print("╚" + "═" * 62 + "╝")
    print()


# ═══════════════════════════════════════════════════════════════════════════════
# Core Pipeline (6 Phases)
# ═══════════════════════════════════════════════════════════════════════════════

def run_pipeline(ahu_data: dict) -> dict:
    """
    Jalankan pipeline 6-phase untuk satu perusahaan.

    Args:
        ahu_data: dict profil AHU yang sudah dimuat

    Returns:
        dict { kyb_output, hcat_result, json_path, pdf_path }
    """
    start_ms = int(time.time() * 1000)
    company_name = ahu_data.get("company", {}).get("name", "UNKNOWN")

    # ──────────────────────────────────────────────────────────────────────
    # PHASE 1: Data Ingestion & Configuration
    # ──────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("📥  PHASE 1: DATA INGESTION & CONFIGURATION")
    print("=" * 62)

    # Extract Top 5 UBO
    top5_ubo = extract_top5_ubo(ahu_data)
    metadata = get_company_metadata(ahu_data)

    # Load PPATK entries
    ppatk_entries = load_all_ppatk()

    # Screen PPATK
    entities_to_check = [company_name]
    for ubo in top5_ubo:
        if ubo.get("name"):
            entities_to_check.append(ubo["name"])

    ppatk_summary = screen_ppatk(entities_to_check, ppatk_entries)

    if ppatk_summary["total_hits"] == 0:
        print(f"   ✅ PPATK: Bersih ({ppatk_summary['total_checked']} entitas diperiksa)")
    else:
        flag = "🚨" if ppatk_summary["has_active_sanctions"] else "⚠️"
        print(f"   {flag} PPATK: {ppatk_summary['total_hits']} hit terdeteksi!")

    # KBLI codes
    kbli_codes = [
        g.get("code", "") for g in ahu_data.get("companyGoals", [])
    ]

    # ──────────────────────────────────────────────────────────────────────
    # PHASE 2: SIPP Scraping & Structuring
    # ──────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("⚖️  PHASE 2: SIPP SCRAPING & STRUCTURING")
    print("=" * 62)

    shareholder_names = [ubo.get("name", "") for ubo in top5_ubo if ubo.get("name")]
    sipp_cases = run_sipp_scraping(company_name, shareholder_names)

    # ──────────────────────────────────────────────────────────────────────
    # PHASE 3: Internet Checking (OSINT) — Corporate & UBO
    # ──────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("🌐  PHASE 3: INTERNET CHECKING (OSINT)")
    print("=" * 62)

    osint_result = run_osint_research(company_name, top5_ubo, kbli_codes)

    # ──────────────────────────────────────────────────────────────────────
    # PHASE 4: Agentic Fusion & Risk Scoring
    # ──────────────────────────────────────────────────────────────────────
    kyb_output = run_fusion(
        ahu_data=ahu_data,
        ppatk_summary=ppatk_summary,
        sipp_cases=sipp_cases,
        osint_result=osint_result,
        start_time_ms=start_ms,
    )

    kyb_dict = kyb_output.model_dump()

    # ──────────────────────────────────────────────────────────────────────
    # PHASE 5: HCAT Evaluation (Validation)
    # ──────────────────────────────────────────────────────────────────────
    hcat_result = None
    try:
        raw_contexts = [
            json.dumps(ahu_data, ensure_ascii=False),
            json.dumps(ppatk_summary, ensure_ascii=False),
            json.dumps(sipp_cases, ensure_ascii=False),
            json.dumps(osint_result, ensure_ascii=False),
        ]

        evaluator = HCATEvaluator()
        hcat_result = evaluator.run_evaluation(raw_contexts, kyb_dict)
    except Exception as e:
        print(f"\n   ⚠️ HCAT evaluation dilewati: {e}")

    # ──────────────────────────────────────────────────────────────────────
    # PHASE 6: PDF Generation
    # ──────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 62)
    print("📄  PHASE 6: PDF GENERATION")
    print("=" * 62)

    json_path = save_json(kyb_dict)
    pdf_path = generate_pdf(kyb_dict, hcat_result=hcat_result)

    # ──────────────────────────────────────────────────────────────────────
    # SUMMARY
    # ──────────────────────────────────────────────────────────────────────
    scoring = kyb_output.ai_risk_scoring
    spider = kyb_output.spider_web_analysis

    print("\n" + "=" * 62)
    print("📑  RINGKASAN OUTPUT KYB INTELLIGENCE REPORT")
    print("=" * 62)
    print(f"   Perusahaan           : {kyb_output.corporate_entity.name}")
    print(f"   ID Investigasi       : {kyb_output.metadata.investigation_id}")
    print(f"   Risk Level           : {scoring.overall_risk_level}")
    print(f"   Contamination Score  : {scoring.risk_contamination_score}/100")
    print(f"   Score Breakdown      :")
    print(f"      AML Risk          : {scoring.score_breakdown.aml_risk}/50")
    print(f"      Legal Risk        : {scoring.score_breakdown.legal_risk}/20")
    print(f"      Reputation Risk   : {scoring.score_breakdown.reputation_risk}/20")
    print(f"      Ownership Risk    : {scoring.score_breakdown.ownership_risk}/25")
    print(f"   Dimensi Intelligence : {len(kyb_output.intelligence_data)}")
    print(f"   Contamination Paths  : {spider.total_contamination_paths}")
    print(f"   Rekomendasi          : {kyb_output.ai_recommendation.action}")

    if hcat_result:
        print(f"   HCAT Confidence      : {hcat_result.get('hcat_confidence_pct', '?')}%")

    print(f"\n   ✅ JSON  : {json_path}")
    print(f"   ✅ PDF   : {pdf_path}")

    if hcat_result:
        print(f"   ✅ HCAT  : validation_reports/")

    # Intermediate outputs
    print(f"   📂 SIPP  : data/output/sipp_scraped/")
    print(f"   📂 OSINT : data/output/internet_osint/")

    print("\n" + "╔" + "═" * 62 + "╗")
    print("║" + " PIPELINE SELESAI ".center(62) + "║")
    print("╚" + "═" * 62 + "╝")

    return {
        "kyb_output": kyb_dict,
        "hcat_result": hcat_result,
        "json_path": json_path,
        "pdf_path": pdf_path,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CLI / Interactive Modes
# ═══════════════════════════════════════════════════════════════════════════════

def mode_json(json_path: str):
    """Mode CLI: Load dari file JSON AHU."""
    print(f"\n📂 Memuat file AHU: {json_path}")
    ahu_data = load_ahu_json(json_path)
    company = ahu_data.get("company", {}).get("name", "?")
    print(f"🎯 Target: {company}")
    print("─" * 62)
    return run_pipeline(ahu_data)


def mode_company(company_name: str, nib: str = None):
    """Mode CLI: Cari di folder data/input/ahu/ berdasarkan nama."""
    print(f"\n🎯 Target: {company_name}" + (f" (NIB: {nib})" if nib else ""))
    ahu_data = find_ahu_by_name(company_name)
    if "error" in ahu_data:
        print(f"\n❌ {ahu_data['error']}")
        sys.exit(1)
    print("─" * 62)
    return run_pipeline(ahu_data)


def mode_interactive():
    """Mode interaktif: menu pilihan."""
    print("📋 PILIH MODE INPUT DATA:")
    print("─" * 44)
    print("  [1] Cari nama perusahaan di folder data/input/ahu/")
    print("  [2] Input path file JSON AHU")
    print("─" * 44)

    while True:
        choice = input("\n🔹 Pilih mode (1/2): ").strip()
        if choice in ["1", "2"]:
            break
        print("   ⚠️ Input tidak valid.")

    if choice == "1":
        # Tampilkan perusahaan tersedia
        available = scan_ahu_folder()
        if available:
            print("\n   📋 Perusahaan tersedia:")
            for i, name in enumerate(list(available.keys())[:10], 1):
                print(f"      {i}. {name}")

        company = input("\n   Nama perusahaan: ").strip()
        if not company:
            print("   ⚠️ Nama wajib diisi!")
            sys.exit(1)

        ahu_data = find_ahu_by_name(company)
        if "error" in ahu_data:
            print(f"\n❌ {ahu_data['error']}")
            sys.exit(1)

    elif choice == "2":
        path = input("\n   Path file JSON AHU: ").strip().strip('"')
        if not os.path.isfile(path):
            print(f"   ⚠️ File tidak ditemukan: {path}")
            sys.exit(1)
        ahu_data = load_ahu_json(path)

    company = ahu_data.get("company", {}).get("name", "?")
    print(f"\n🎯 Target: {company}")
    print("─" * 62)
    return run_pipeline(ahu_data)


# ═══════════════════════════════════════════════════════════════════════════════
# Main Entry
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="AI-KYB Intelligence Pipeline v3.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Contoh:
  python run_pipeline.py --json data/input/ahu/01__aneka_bintang_gading.json
  python run_pipeline.py --company "ANEKA BINTANG GADING" --nib 1234567890
  python run_pipeline.py --interactive
        """,
    )
    parser.add_argument("--json", metavar="PATH", help="Path file JSON AHU")
    parser.add_argument("--company", metavar="NAME", help="Nama perusahaan")
    parser.add_argument("--nib", metavar="NIB", help="Nomor Induk Berusaha")
    parser.add_argument("--interactive", action="store_true", help="Mode interaktif")

    args = parser.parse_args()

    print_banner()

    if args.json:
        mode_json(args.json)
    elif args.company:
        mode_company(args.company, args.nib)
    else:
        mode_interactive()


if __name__ == "__main__":
    main()