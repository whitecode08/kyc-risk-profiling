import json
import time
from google import genai
from google.genai import types
from src.core.config import Config
from src.core.state import (
    PipelineState, CompanyProfileOutput, RiskAssessment,
    UBOAnalysis, LitigationSummary, CriticFeedback,
    InternetResearchResult, InputMode
)
from src.tools.ahu_scraper import AHUScraperTool
from src.tools.sipp_scraper import SIPPScraperTool
from src.tools.ppatk_tool import PPATKTool
from src.tools.internet_researcher import InternetResearchTool

client = genai.Client(api_key=Config.GEMINI_API_KEY)


def researcher_agent(state: PipelineState) -> PipelineState:
    """
    Researcher Agent - Mengumpulkan data mentah dari sumber-sumber OSINT.
    
    Menggunakan Flash model (Heavy I/O) untuk efisiensi biaya per TSD.
    Tugas: Tarik data dari AHU API + SIPP MA untuk perusahaan dan semua pengurus.
    
    Mendukung 2 mode input:
    1. NIB Lookup - cari data otomatis dari database AHU
    2. Manual Upload - data sudah tersedia di state (dari PDF/JSON)
    """
    print(f"\n🔍 [Researcher Agent] Menarik data dari sumber OSINT untuk: {state.company_name}")
    
    # Lock anchor parameters (anti-bias per TSD)
    if not state.anchor_locked:
        state.anchor_locked = True
        print(f"   🔐 Anchor Parameter DIKUNCI: Nama='{state.company_name}'" + 
              (f", NIB='{state.nib}'" if state.nib else ""))

    # ============================================
    # Step 1: Tarik data profil perusahaan dari AHU
    # ============================================
    print("   📋 Sumber: Ditjen AHU (Profil Perusahaan)")
    
    if state.input_mode == InputMode.NIB_LOOKUP:
        # Mode 1: Lookup otomatis via NIB + Nama
        state.raw_ahu_data = AHUScraperTool.lookup(
            company_name=state.company_name,
            nib=state.nib
        )
    elif not state.raw_ahu_data:
        # Mode 2: Manual upload - data seharusnya sudah di-set ke state sebelumnya
        # Jika belum ada, coba lookup dulu
        state.raw_ahu_data = AHUScraperTool.get_company_profile(state.company_name)

    if "error" in state.raw_ahu_data:
        print(f"   ⚠️ AHU: {state.raw_ahu_data['error']}")
        return state

    company_name = state.raw_ahu_data.get("company", {}).get("name", state.company_name)
    shareholders = state.raw_ahu_data.get("shareholders", [])
    print(f"   ✅ AHU: Ditemukan profil {company_name} dengan {len(shareholders)} pemegang saham")

    # ============================================
    # Step 2: Cek litigasi perusahaan di SIPP MA
    # ============================================
    if not state.raw_sipp_data:
        # Hanya cek SIPP jika data belum di-load manual
        print("   📋 Sumber: SIPP Mahkamah Agung (Riwayat Litigasi)")
        company_litigation = SIPPScraperTool.check_litigation(state.company_name)
        if company_litigation:
            state.raw_sipp_data.extend(company_litigation)
            print(f"   ⚠️ SIPP: Ditemukan {len(company_litigation)} kasus litigasi untuk perusahaan")

        # Step 3: Cek litigasi setiap pemegang saham / pengurus
        for member in shareholders:
            member_name = member.get("name", "")
            if member_name:
                lawsuits = SIPPScraperTool.check_litigation(member_name)
                if lawsuits:
                    # Hindari duplikat jika kasus yang sama sudah ada
                    existing_case_ids = {c.get("nomor_perkara") for c in state.raw_sipp_data}
                    new_lawsuits = [l for l in lawsuits if l.get("nomor_perkara") not in existing_case_ids]
                    if new_lawsuits:
                        state.raw_sipp_data.extend(new_lawsuits)
                        print(f"   ⚠️ SIPP: Ditemukan {len(new_lawsuits)} kasus tambahan untuk {member_name}")
    else:
        print(f"   📋 SIPP: Menggunakan {len(state.raw_sipp_data)} data litigasi yang sudah dimuat")

    total_cases = len(state.raw_sipp_data)
    if total_cases == 0:
        print("   ✅ SIPP: Tidak ditemukan riwayat litigasi")
    else:
        print(f"   📊 Total kasus litigasi unik: {total_cases}")

    # ============================================
    # Step 4: Screening PPATK DTTOT
    # ============================================
    if not state.raw_ppatk_data:
        print("   📋 Sumber: PPATK DTTOT (Daftar Sanksi Keuangan Terarah)")
        # Kumpulkan semua nama yang perlu dicek: perusahaan + pemegang saham/pengurus
        entities_to_check = [state.company_name]
        for member in shareholders:
            member_name = member.get("name", "")
            if member_name:
                entities_to_check.append(member_name)

        ppatk_summary = PPATKTool.get_screening_summary(entities_to_check)
        state.raw_ppatk_data = ppatk_summary

        if ppatk_summary["total_hits"] == 0:
            print(f"   ✅ PPATK: Tidak ditemukan nama dalam daftar DTTOT ({ppatk_summary['total_checked']} entitas diperiksa)")
        else:
            sanction_flag = "🚨" if ppatk_summary["has_active_sanctions"] else "⚠️"
            print(f"   {sanction_flag} PPATK: {ppatk_summary['total_hits']} entitas terdeteksi dalam daftar DTTOT!")
            for entity, hits in ppatk_summary["hits"].items():
                print(f"      - {entity}: {len(hits)} entri ({', '.join(h.get('kategori','?') for h in hits)})")
    else:
        print(f"   📋 PPATK: Menggunakan data screening yang sudah dimuat ({state.raw_ppatk_data.get('total_hits', 0)} hit)")

    return state


def internet_research_agent(state: PipelineState) -> PipelineState:
    """
    Internet Research Agent - Melakukan riset internet (OSINT) menggunakan
    Gemini Google Search Grounding.
    
    Tugas:
    1. Adverse Media Screening - berita negatif, fraud, skandal
    2. Sanctions List Screening - OFAC, UN, EU, PPATK
    3. PEP Detection - Politically Exposed Person
    4. Business Legitimacy Verification
    """
    if "error" in state.raw_ahu_data:
        print("\n🌐 [Internet Research] Dilewati - data AHU tidak tersedia")
        return state

    shareholders = state.raw_ahu_data.get("shareholders", [])
    kbli_codes = [
        goal.get("code", "") 
        for goal in state.raw_ahu_data.get("companyGoals", [])
    ]

    state.internet_research = InternetResearchTool.research_company(
        company_name=state.company_name,
        shareholders=shareholders,
        kbli_codes=kbli_codes,
        nib=state.nib
    )

    return state


def drafter_agent(state: PipelineState) -> PipelineState:
    """
    Drafter Agent - Menyusun data mentah menjadi JSON terstruktur + kalkulasi risiko.
    
    Menggunakan Flash model sesuai TSD cost optimization.
    Tugas: Buat structured company profile + risk assessment dari raw data.
    Sekarang juga memperhitungkan hasil internet research.
    """
    print(f"\n✍️  [Drafter Agent] Menyusun Profil & Analisis Risiko (Revisi: {state.revision_count})")

    # Siapkan data mentah sebagai konteks
    ahu_context = json.dumps(state.raw_ahu_data, ensure_ascii=False)
    sipp_context = json.dumps(state.raw_sipp_data, ensure_ascii=False)

    # Siapkan konteks PPATK
    ppatk_context = ""
    if state.raw_ppatk_data:
        ppatk_context = json.dumps(state.raw_ppatk_data, ensure_ascii=False)

    # Siapkan konteks internet research
    internet_context = ""
    if state.internet_research:
        internet_context = json.dumps(state.internet_research.model_dump(), ensure_ascii=False)

    # Hitung total modal disetor untuk referensi UBO
    paid_up_capital = 0
    paid_up_str = state.raw_ahu_data.get("paidUpStock", "")
    if paid_up_str:
        try:
            paid_up_capital = int(paid_up_str.replace("Rp. ", "").replace(",", "").replace(".", "").strip())
        except ValueError:
            paid_up_capital = 500000000  # fallback

    prompt = f"""
    Anda adalah analis KYB (Know Your Business) senior. Analisis data perusahaan berikut dan hasilkan penilaian risiko yang komprehensif.

    === DATA PROFIL PERUSAHAAN (dari Ditjen AHU) ===
    {ahu_context}

    === DATA LITIGASI (dari SIPP Mahkamah Agung) ===
    {sipp_context}

    === SCREENING PPATK DTTOT (Sanksi Keuangan Terarah) ===
    {ppatk_context if ppatk_context else "Tidak ada data PPATK tersedia. Asumsikan tidak ada hit sanksi."}

    === HASIL RISET INTERNET (Google Search Grounding) ===
    {internet_context if internet_context else "Tidak ada temuan internet yang signifikan."}

    === INSTRUKSI ANALISIS RISIKO ===

    1. **UBO Analysis (Ultimate Beneficial Owner)**:
       - Modal disetor total: {paid_up_capital}
       - Hitung persentase kepemilikan setiap pemegang saham: (numberOfShares / {paid_up_capital}) * 100
       - Identifikasi siapa yang memiliki ≥25% (threshold UBO per regulasi PPATK)
       - Perhatikan juga kepemilikan melalui badan hukum (PT) yang mungkin menyembunyikan UBO

    2. **Litigation Risk**:
       - Evaluasi setiap kasus litigasi: jenis, status, nilai gugatan
       - Kasus Wanprestasi menunjukkan risiko gagal bayar
       - Status "Selesai - Mediasi Berhasil" lebih baik dari putusan pengadilan

    3. **Business Activity Risk (KBLI)**:
       - Evaluasi apakah KBLI perusahaan termasuk sektor berisiko tinggi
       - Kelab malam, bar, minuman beralkohol = indikator risiko tinggi untuk AML/TPPU

    4. **PPATK DTTOT Sanctions Risk** (KRITIS):
       - Jika `has_active_sanctions = true` dalam data PPATK, WAJIB tambahkan +40 ke skor risiko
       - Setiap entitas yang terdeteksi WAJIB disebutkan eksplisit di key_findings
       - Kategori DTTOT (terorisme) = risiko lebih tinggi dari TPPU
       - Jika ada hit dari daftar internasional (OFAC, UN SC), WAJIB High Risk (skor ≥76)

    5. **Internet Research Risk**:
       - Pertimbangkan temuan adverse media dalam skor risiko
       - Jika ada hit sanksi (OFAC/UN/EU/PPATK), WAJIB tambahkan +30 ke skor risiko
       - Jika ada PEP terdeteksi, WAJIB tambahkan +15 ke skor risiko
       - Masukkan temuan internet ke dalam key_findings

    6. **Risk Scoring (1-100)**:
       - 1-25: Low Risk
       - 26-50: Moderate Risk
       - 51-75: Moderate-High Risk
       - 76-100: High Risk

       Faktor penambah skor:
       - UBO >25% (+15)
       - Litigasi aktif (+20), Litigasi selesai (+10)
       - KBLI berisiko tinggi (+15)
       - Pemegang saham badan hukum tanpa transparansi (+10)
       - PPATK DTTOT aktif (+40), PPATK TPPU (+20)
       - Adverse media High (+20), Medium (+10)
       - Sanksi internasional/internet (+30)
       - PEP (+15)

    7. **Regulatory Recommendation**:
       - Low Risk: "Setujui"
       - Moderate Risk: "Setujui dengan Monitoring"
       - Moderate-High Risk: "Enhanced Due Diligence (EDD) Required"
       - High Risk: "Tolak / Eskalasi ke Komite"

    8. **Status Hukum Perusahaan (PENTING)**:
       - Status "TERTUTUP" berarti Perseroan Terbatas Tertutup (Private Company, bukan Tbk).
         Ini adalah status NORMAL dan BUKAN indikator risiko. DILARANG menyebut status TERTUTUP
         sebagai faktor risiko tinggi atau perusahaan tutup.

    {f"CATATAN REVISI SEBELUMNYA (WAJIB diperbaiki): {state.critic_feedback}" if state.critic_feedback else ""}
    {f"FIELD YANG MASIH KOSONG: {', '.join(state.missing_fields)}" if state.missing_fields else ""}

    Berikan output dalam format JSON yang valid.
    """

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=Config.HEAVY_IO_MODEL,  # Flash model per TSD
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=RiskAssessment,
                    temperature=0.2
                )
            )

            risk_assessment = RiskAssessment.model_validate_json(response.text)

            # Bangun CompanyProfileOutput dari raw AHU data + risk assessment + internet research
            profile_data = {
                "isProfileComplete": True,
                **{k: v for k, v in state.raw_ahu_data.items()
                   if k in ["company", "companyAddress", "companyGoals", "notary",
                            "baseStock", "issuedStock", "paidUpStock", "shareholders"]},
                "risk_assessment": risk_assessment.model_dump(),
                "internet_research": state.internet_research.model_dump() if state.internet_research else None
            }

            state.company_profile = CompanyProfileOutput.model_validate(profile_data)
            
            print(f"   📊 Risk Score: {risk_assessment.overall_risk_score}/100")
            print(f"   📊 Classification: {risk_assessment.risk_classification}")
            print(f"   📊 Recommendation: {risk_assessment.regulatory_recommendation}")
            return state

        except Exception as e:
            print(f"   [!] Gagal memanggil API ({e}). Mencoba ulang dalam 3 detik... ({attempt + 1}/3)")
            time.sleep(3)

    raise RuntimeError("Drafter Agent gagal mendapatkan respons dari Gemini setelah 3 kali percobaan.")


def critic_agent(state: PipelineState) -> PipelineState:
    """
    Critic Agent - Memvalidasi kelayakan profil dan analisis risiko.
    
    Menggunakan Pro/Complex Reasoning model sesuai TSD.
    Guardrails: Validasi kelengkapan data, akurasi kalkulasi UBO, dan konsistensi risk scoring.
    Sekarang juga memvalidasi bahwa temuan internet research tercermin dalam skor risiko.
    """
    print("\n🕵️‍♂️ [Critic Agent] Memvalidasi kelayakan profil dan analisis risiko...")

    if not state.company_profile:
        state.is_valid = False
        state.critic_feedback = "Company profile belum tersusun. Drafter harus menyusun profil terlebih dahulu."
        return state

    profile_json = state.company_profile.model_dump_json(indent=2)
    raw_ahu = json.dumps(state.raw_ahu_data, ensure_ascii=False)
    raw_sipp = json.dumps(state.raw_sipp_data, ensure_ascii=False)

    # Tambahkan konteks PPATK untuk validasi
    ppatk_context = ""
    if state.raw_ppatk_data:
        ppatk_context = f"""
    === SCREENING PPATK DTTOT ===
    {json.dumps(state.raw_ppatk_data, ensure_ascii=False)}
    """

    # Tambahkan konteks internet research untuk validasi
    internet_context = ""
    if state.internet_research:
        internet_context = f"""
    === HASIL RISET INTERNET ===
    {json.dumps(state.internet_research.model_dump(), ensure_ascii=False)}
    """

    prompt = f"""
    Anda adalah Auditor Kepatuhan Senior. Evaluasi profil perusahaan dan analisis risiko berikut.

    === PROFIL & RISK ASSESSMENT YANG DISUSUN ===
    {profile_json}

    === DATA MENTAH ASLI (GROUND TRUTH) ===
    AHU: {raw_ahu}
    SIPP: {raw_sipp}
    {ppatk_context}
    {internet_context}

    === GUARDRAILS VALIDASI (SEMUA HARUS TERPENUHI) ===

    1. **Kelengkapan Data Profil**:
       - company.name HARUS terisi
       - shareholders HARUS mencakup SEMUA pemegang saham dari data AHU (bandingkan jumlahnya)
       - companyGoals HARUS mencakup SEMUA KBLI dari data AHU

    2. **Akurasi UBO Analysis**:
       - Periksa apakah perhitungan persentase saham benar
       - Persentase ini HARUS disebutkan eksplisit di key_findings

    3. **Konsistensi Litigasi**:
       - Jika ADA riwayat litigasi di data SIPP, hal ini WAJIB tercantum di key_findings
       - Jika ada litigasi Wanprestasi, risk_classification TIDAK BOLEH "Low Risk"

    4. **Konsistensi Risk Scoring**:
       - Perusahaan dengan KBLI kelab malam/bar/alkohol + litigasi = MINIMAL "Moderate Risk"
       - Risk score harus konsisten dengan classification

    5. **Regulatory Recommendation**:
       - HARUS sesuai dengan risk classification
       - Moderate-High Risk atau lebih = WAJIB "EDD Required"

    6. **PPATK DTTOT Consistency** (KRITIS):
       - Jika data PPATK menunjukkan `has_active_sanctions = true`, risk score HARUS ≥ 76 (High Risk)
       - Setiap entitas yang terdeteksi WAJIB disebutkan di key_findings dengan format:
         "[PPATK HIT] <nama>: <kategori> - <dasar_penetapan>"
       - Jika ada sanksi dari daftar internasional (OFAC/UN SC), risk_classification HARUS "High Risk"

    7. **Internet Research Consistency**:
       - Jika ada temuan adverse media dengan severity High, risk score HARUS > 50
       - Jika ada hit sanksi internasional, WAJIB ada di key_findings
       - Jika ada PEP terdeteksi, WAJIB ada di key_findings dan risk score bertambah

    Jika SEMUA guardrails terpenuhi, set is_valid = true.
    Jika ADA YANG KURANG, set is_valid = false, berikan feedback koreksi tegas, dan list field yang bermasalah.
    """

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=Config.COMPLEX_REASONING_MODEL,  # Pro model per TSD
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CriticFeedback,
                    temperature=0.1
                )
            )
            feedback = CriticFeedback.model_validate_json(response.text)
            state.is_valid = feedback.is_valid
            state.critic_feedback = feedback.feedback
            state.missing_fields = feedback.missing_fields

            if state.is_valid:
                print("   ✅ Profil Lulus Validasi Guardrails!")
            else:
                print(f"   ❌ Profil Ditolak. Alasan: {state.critic_feedback}")
                if state.missing_fields:
                    print(f"   📋 Fields bermasalah: {', '.join(state.missing_fields)}")
            return state

        except Exception as e:
            print(f"   [!] Gagal memanggil API ({e}). Mencoba ulang... ({attempt + 1}/3)")
            time.sleep(3)

    raise RuntimeError("Critic Agent gagal mendapatkan respons dari Gemini setelah 3 kali percobaan.")