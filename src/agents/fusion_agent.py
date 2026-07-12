"""
Fusion Agent — AI Researcher & AI Critic (Scoring)
====================================================
Phase 4 dari KYB Pipeline (otak utama proyek):
1. AI Researcher: Membaca 4 file JSON (AHU, PPATK, SIPP, OSINT),
                  merangkum narasi komprehensif terkait kondisi nasabah.
2. AI Critic:     Membaca narasi dari Researcher, membandingkannya
                  dengan risk_weights.json, menghitung final Risk Score
                  dan justifikasi skor.

Output: KYBInvestigationOutput (final_summary.json)

Prompt Engineering Notes (v3.1):
- Uses explanation-first sequencing (reasoning BEFORE scoring)
- Uses Pydantic response_schema enforcement via Gemini API
- Uses enum constraints for categorical fields
- Guardrails calibrated per FATF RBA, POJK 8/2023, PPATK NRA 2023
"""

import json
import time
from datetime import datetime, timezone
from typing import List, Optional, Union
from enum import Enum

from pydantic import BaseModel, Field
from anthropic import Anthropic

from src.config import (
    ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL,
    HEAVY_IO_MODEL, COMPLEX_REASONING_MODEL,
    RISK_WEIGHTS, extract_text_from_response
)

client = Anthropic(api_key=ANTHROPIC_API_KEY, base_url=ANTHROPIC_BASE_URL)


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Models — KYB Investigation Output (v3.1)
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Company Profile ──────────────────────────────────────────────────────────

class StockInfo(BaseModel):
    classification: str = Field(default="", description="Klasifikasi saham")
    price_per_share: str = Field(default="", description="Harga per lembar saham")
    number_of_shares: str = Field(default="", description="Jumlah lembar saham")
    grand_total: str = Field(default="", description="Total nilai saham")


class CompanyProfile(BaseModel):
    """Profil lengkap perusahaan dari data AHU."""
    name: str = Field(description="Nama perusahaan")
    sk_number: str = Field(default="", description="Nomor SK AHU")
    sk_date: str = Field(default="", description="Tanggal SK")
    company_type: str = Field(default="", description="Jenis perusahaan (PMDN/PMA)")
    status: str = Field(default="", description="Status badan hukum (TERTUTUP = PT Tertutup, BUKAN tutup)")
    time_period: str = Field(default="", description="Jangka waktu perusahaan")
    transaction_type: str = Field(default="", description="Jenis transaksi terakhir")
    address: str = Field(default="", description="Alamat lengkap")
    province: str = Field(default="", description="Provinsi")
    regency: str = Field(default="", description="Kabupaten/Kota")
    base_stock: StockInfo = Field(default_factory=StockInfo, description="Modal dasar")
    issued_stock: StockInfo = Field(default_factory=StockInfo, description="Modal ditempatkan")
    paid_up_stock: str = Field(default="", description="Modal disetor")
    business_description: str = Field(
        default="", 
        description="Executive summary / deskripsi bisnis naratif (2-3 paragraf) yang merangkum latar belakang, operasional, dan performa perusahaan berdasarkan data AHU dan OSINT."
    )


# ─── Company Goals (KBLI) ────────────────────────────────────────────────────

class CompanyGoal(BaseModel):
    no: int = Field(description="Nomor urut")
    code: str = Field(description="Kode KBLI")
    name: str = Field(description="Nama kegiatan usaha")
    description: str = Field(default="", description="Deskripsi kegiatan usaha")
    is_high_risk: bool = Field(default=False, description="Apakah KBLI termasuk high-risk (cash-intensive, TBML, etc.)")


# ─── Shareholders / UBO ──────────────────────────────────────────────────────

class ShareholderUBO(BaseModel):
    name: str = Field(description="Nama pemegang saham")
    position: str = Field(default="-", description="Jabatan")
    number_of_shares: int = Field(default=0, description="Jumlah lembar saham")
    percentage: float = Field(default=0.0, description="Persentase kepemilikan")
    address: str = Field(default="", description="Alamat")
    country: str = Field(default="Indonesia", description="Negara")
    is_corporate: bool = Field(default=False, description="Apakah pemegang saham badan hukum (PT)")
    is_ubo: bool = Field(default=False, description="Apakah termasuk UBO (>=25%)")


# ─── Intelligence Data ───────────────────────────────────────────────────────

class IntelligenceDataPoint(BaseModel):
    attribute: str = Field(description="Nama atribut")
    value: Union[str, bool, int, float, List[str], List[dict], dict, None] = Field(
        description="Nilai atribut"
    )


class IntelligenceDimension(BaseModel):
    dimension: str = Field(description="Nama dimensi analisis")
    source_system: str = Field(description="Sistem sumber data")
    data_points: List[IntelligenceDataPoint] = Field(default_factory=list)
    finding: str = Field(description="Narasi temuan dimensi dalam Bahasa Indonesia")
    risk_weight: int = Field(description="Bobot kontribusi (0-50)")
    category: str = Field(description="Kategori risiko: Ownership_and_Industry_Risk|AML_Risk|Legal_Risk|Reputation_Risk")


# ─── Risk Scoring ────────────────────────────────────────────────────────────

class ScoreBreakdown(BaseModel):
    aml_risk: int = Field(default=0, description="Skor AML (0-50)")
    legal_risk: int = Field(default=0, description="Skor Legal (0-20)")
    reputation_risk: int = Field(default=0, description="Skor Reputation (0-20)")
    ownership_risk: int = Field(default=0, description="Skor Ownership (0-25)")


class AIRiskScoring(BaseModel):
    overall_risk_level: str = Field(
        description="Tingkat risiko: LOW|MODERATE|MODERATE-HIGH|HIGH"
    )
    risk_contamination_score: int = Field(description="Skor 0-100")
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    scoring_reasoning: str = Field(
        default="",
        description="Penjelasan detail MENGAPA setiap komponen skor diberikan nilai tersebut. "
                    "Harus menjelaskan faktor apa yang menambah/mengurangi skor per dimensi."
    )


# ─── Spider Web Analysis ─────────────────────────────────────────────────────

class ProblematicEntity(BaseModel):
    entity_name: str
    connection_type: str = Field(
        description="Tipe koneksi: Directorship|Shareholder|Beneficiary|Associate"
    )
    risk_flag: str = Field(
        description="Flag risiko: PPATK_STR|PPATK_DTTOT|SIPP_LITIGATION|PEP|ADVERSE_MEDIA|"
                    "CORPORATE_UBO|OFAC_SDN|UN_SECURITY_COUNCIL|NOMINEE_SHAREHOLDER|"
                    "SHELL_COMPANY|TBML_SECTOR|HIGH_RISK_GEOGRAPHY"
    )


class SpiderWebAnalysis(BaseModel):
    total_contamination_paths: int = Field(default=0)
    problematic_entities_connected: List[ProblematicEntity] = Field(default_factory=list)


# ─── AI Recommendation ───────────────────────────────────────────────────────

class AIRecommendation(BaseModel):
    action: str = Field(
        description="Aksi rekomendasi: APPROVE|APPROVE_WITH_MONITOR|REQUIRE_EDD|ESCALATE_FOR_EDD|REJECT"
    )
    narrative: str = Field(description="Narasi rekomendasi dalam Bahasa Indonesia")
    required_documents: List[str] = Field(default_factory=list)
    risk_mitigation: List[str] = Field(
        default_factory=list,
        description="Langkah-langkah mitigasi risiko yang disarankan dalam Bahasa Indonesia"
    )


# ─── Metadata ─────────────────────────────────────────────────────────────────

class CorporateEntity(BaseModel):
    name: str
    sk_number: str = ""
    company_type: str = ""


class InvestigationMetadata(BaseModel):
    investigation_id: str
    timestamp: str
    processing_time_ms: int = 0
    status: str = "COMPLETED"


# ─── Final Output ─────────────────────────────────────────────────────────────

class KYBInvestigationOutput(BaseModel):
    """Model output final KYB Investigation v3.1 — diperluas dengan profil, KBLI, UBO."""
    metadata: InvestigationMetadata
    corporate_entity: CorporateEntity
    company_profile: CompanyProfile
    company_goals: List[CompanyGoal] = Field(default_factory=list)
    shareholders_ubo: List[ShareholderUBO] = Field(default_factory=list)
    ai_risk_scoring: AIRiskScoring
    intelligence_data: List[IntelligenceDimension] = Field(default_factory=list)
    spider_web_analysis: SpiderWebAnalysis = Field(default_factory=SpiderWebAnalysis)
    ai_recommendation: AIRecommendation


class CriticFeedback(BaseModel):
    """Feedback dari AI Critic."""
    is_valid: bool = Field(description="True jika memenuhi semua guardrails")
    feedback: str = Field(description="Detail kritik/koreksi jika is_valid=false, atau konfirmasi jika true")
    missing_fields: List[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# AI Researcher
# ═══════════════════════════════════════════════════════════════════════════════

def _build_researcher_prompt(
    ahu_data: dict,
    ppatk_summary: dict,
    sipp_cases: list,
    osint_result: dict,
    revision_feedback: str = "",
    missing_fields: list = None,
) -> str:
    """Build the AI Researcher prompt with explanation-first sequencing."""

    # Prepare contexts
    ahu_context = json.dumps(ahu_data, ensure_ascii=False)
    sipp_context = json.dumps(sipp_cases, ensure_ascii=False) if sipp_cases else "[]"
    ppatk_context = json.dumps(ppatk_summary, ensure_ascii=False) if ppatk_summary else "{}"
    osint_context = json.dumps(osint_result, ensure_ascii=False) if osint_result else "{}"

    # Weight config
    dim_weights = RISK_WEIGHTS.get("dimensions", {})
    score_adders = RISK_WEIGHTS.get("score_adders", {})
    kbli_high_risk = RISK_WEIGHTS.get("kbli_high_risk", {}).get("codes", [])

    # Parse paid up capital
    paid_up_str = ahu_data.get("paidUpStock", "")
    try:
        paid_up_capital = int(
            paid_up_str.replace("Rp. ", "").replace(",", "").replace(".", "").strip()
        )
    except (ValueError, AttributeError):
        paid_up_capital = 500_000_000

    # Build score adders reference
    adders_ref = "\n".join(
        f"  - {k}: +{v}" for k, v in score_adders.items()
        if not k.startswith("_")
    )

    prompt = f"""
### PERSONA
Anda adalah Senior KYB/AML Compliance Analyst di divisi Manajemen Risiko sebuah Lembaga Jasa Keuangan.
Anda bertugas membuat laporan investigasi KYB (Know Your Business) yang komprehensif dan akurat.

### DATA SUMBER (GROUND TRUTH)
Gunakan HANYA data berikut. JANGAN menambahkan informasi yang tidak ada di data ini.

=== 1. PROFIL PERUSAHAAN (Ditjen AHU) ===
{ahu_context}

=== 2. SCREENING PPATK DTTOT ===
{ppatk_context}

=== 3. DATA LITIGASI (SIPP Mahkamah Agung) ===
{sipp_context}

=== 4. HASIL RISET INTERNET (OSINT) ===
{osint_context}

### INSTRUKSI ANALISIS (STEP-BY-STEP)

**Langkah 1 — Ekstrak Profil Perusahaan & Executive Summary:**
- Salin data profil dari AHU JSON ke company_profile, termasuk baseStock, issuedStock, paidUpStock.
- Tuliskan `business_description` (2-3 paragraf) yang merangkum secara profesional narasi tentang perusahaan ini (bidang usaha utama, posisi di pasar, sekilas performa atau background berdasarkan data OSINT dan KBLI). Gunakan bahasa bisnis yang formal.
- PENTING: Status "TERTUTUP" = PT Tertutup (bukan Tbk), BUKAN berarti perusahaan tutup/bangkrut. JANGAN jadikan ini sebagai faktor risiko.

**Langkah 2 — Ekstrak KBLI (company_goals):**
Salin semua kegiatan usaha dari companyGoals. Tandai is_high_risk=true jika kode KBLI termasuk dalam: {', '.join(kbli_high_risk[:10])}

**Langkah 3 — Ekstrak Shareholders/UBO:**
- Hitung persentase = (numberOfShares / {paid_up_capital}) × 100
- Tandai is_ubo=true jika persentase >= 25%
- Tandai is_corporate=true HANYA jika nama DIAWALI dengan "PT " atau "CV " (prefix), atau DIAKHIRI dengan " PT" atau " CV" (suffix). JANGAN tandai is_corporate hanya karena nama mengandung substring "PT" atau "CV" (contoh: "CIPTA", "ACVB" = BUKAN korporasi)
- Urutkan dari persentase terbesar, jangan dibatasi (masukkan semua pemegang saham ke dalam array)

**Langkah 4 — Analisis 4 Dimensi Risiko:**
Buat intelligence_data dengan TEPAT 4 dimensi:

  1. "Corporate & Industry Profiling" (category: Ownership_and_Industry_Risk, max: {dim_weights.get('Ownership_and_Industry_Risk', {}).get('max_score', 25)})
     - Analisis KBLI, struktur kepemilikan, transparansi UBO
  2. "AML & APU PPT" (category: AML_Risk, max: {dim_weights.get('AML_Risk', {}).get('max_score', 50)})
     - Analisis PPATK DTTOT hits, STR history, sanksi internasional
  3. "Legal & Litigation" (category: Legal_Risk, max: {dim_weights.get('Legal_Risk', {}).get('max_score', 20)})
     - Analisis perkara SIPP: kepailitan, PKPU, perdata, pidana
  4. "Adverse Media & OSINT" (category: Reputation_Risk, max: {dim_weights.get('Reputation_Risk', {}).get('max_score', 20)})
     - Analisis adverse media, PEP, reputasi internet

**Langkah 5 — Hitung Skor Risiko (EXPLANATION FIRST):**
SEBELUM menentukan angka skor, TULISKAN reasoning terlebih dahulu di field scoring_reasoning:
  a. Identifikasi setiap faktor risiko yang ditemukan dari data
  b. Tentukan skor per dimensi berdasarkan faktor yang ditemukan
  c. Jumlahkan: risk_contamination_score = aml_risk + legal_risk + reputation_risk + ownership_risk
  d. Cap pada 100 jika total melebihi 100
  e. Tentukan level: 1-25=LOW, 26-50=MODERATE, 51-75=MODERATE-HIGH, 76-100=HIGH

Score adders reference:
{adders_ref}

**Langkah 6 — Spider Web Analysis:**
- Identifikasi entitas bermasalah yang terhubung dengan perusahaan
- total_contamination_paths = jumlah problematic_entities_connected
- Pemegang saham korporasi (PT) WAJIB masuk dengan flag CORPORATE_UBO

**Langkah 7 — Rekomendasi & Mitigasi:**
- LOW → APPROVE, MODERATE → APPROVE_WITH_MONITOR, MODERATE-HIGH → REQUIRE_EDD, HIGH → ESCALATE_FOR_EDD
- Jika action BUKAN APPROVE: required_documents TIDAK BOLEH kosong
- risk_mitigation: berikan 3-5 langkah mitigasi konkret dalam Bahasa Indonesia

### ATURAN KETAT (GUARDRAILS)
1. risk_contamination_score HARUS = sum(score_breakdown)
2. Jika PPATK has_active_sanctions=true → aml_risk WAJIB >= 40
3. Jika ada OFAC/UN hit → aml_risk WAJIB >= 45
4. Pemegang saham korporasi (PT/CV) → WAJIB spider_web dengan flag CORPORATE_UBO
5. Status TERTUTUP = PT Tertutup, BUKAN risiko
6. Semua narasi finding dan narrative WAJIB dalam Bahasa Indonesia
7. Jangan mengarang data yang tidak ada di sumber
8. PENTING UNTUK LIMITASI TOKEN: Tuliskan semua `finding`, `narrative`, dan `scoring_reasoning` secara SANGAT PADAT dan SINGKAT (maks 1-2 kalimat). Jangan mengulang-ulang data atau bertele-tele agar JSON tidak terpotong (truncated)!

### FORMAT OUTPUT (JSON SCHEMA)
Output HARUS 100% valid JSON sesuai dengan skema berikut:
{json.dumps(KYBInvestigationOutput.model_json_schema(), indent=2)}

{f"### CATATAN REVISI DARI CRITIC: {revision_feedback}" if revision_feedback else ""}
{f"### FIELD BERMASALAH: {', '.join(missing_fields)}" if missing_fields else ""}
"""
    return prompt


def ai_researcher(ahu_data: dict, ppatk_summary: dict,
                  sipp_cases: list, osint_result: dict,
                  start_time_ms: int = 0,
                  revision_feedback: str = "",
                  missing_fields: list = None) -> KYBInvestigationOutput:
    """
    AI Researcher: Membaca 4 sumber JSON sekaligus dan merangkum
    narasi komprehensif → KYBInvestigationOutput.

    Uses explanation-first sequencing for consistent scoring.
    Uses Pydantic response_schema for structural enforcement.
    """
    print(f"\n   🔬 AI Researcher: Menyusun narasi dari 4 sumber data...")

    prompt = _build_researcher_prompt(
        ahu_data, ppatk_summary, sipp_cases, osint_result,
        revision_feedback, missing_fields
    )

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=HEAVY_IO_MODEL,
                max_tokens=16000,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.15,
            )

            raw_text = extract_text_from_response(response)

            # Fail fast if model hit token limit (truncated JSON = invalid)
            if getattr(response, "stop_reason", None) == "max_tokens":
                raise ValueError(
                    "Response truncated (stop_reason=max_tokens). "
                    "JSON tidak lengkap. Coba lagi dengan output lebih ringkas."
                )
            # Strip markdown code fences if present
            import re
            raw_text = re.sub(r'^```(?:json)?\s*', '', raw_text.strip())
            raw_text = re.sub(r'\s*```$', '', raw_text)
            output = KYBInvestigationOutput.model_validate_json(raw_text)

            # Post-process: inject processing time
            elapsed_ms = int(time.time() * 1000) - start_time_ms if start_time_ms else 0
            output.metadata.processing_time_ms = elapsed_ms
            output.metadata.status = "COMPLETED"

            # Ensure corporate_entity is populated from AHU
            if not output.corporate_entity.name:
                output.corporate_entity.name = ahu_data.get("company", {}).get("name", "")
            if not output.corporate_entity.sk_number:
                output.corporate_entity.sk_number = ahu_data.get("company", {}).get("skNumber", "")
            if not output.corporate_entity.company_type:
                output.corporate_entity.company_type = ahu_data.get("company", {}).get("type", "")

            score = output.ai_risk_scoring.risk_contamination_score
            level = output.ai_risk_scoring.overall_risk_level
            action = output.ai_recommendation.action
            print(f"   📊 Score: {score}/100 | Level: {level} | Action: {action}")
            return output

        except Exception as e:
            print(f"   [!] AI Researcher Retry ({attempt+1}/3): {e}")
            time.sleep(3)

    raise RuntimeError("AI Researcher gagal setelah 3 percobaan.")


# ═══════════════════════════════════════════════════════════════════════════════
# AI Critic (Scoring Validation)
# ═══════════════════════════════════════════════════════════════════════════════

def ai_critic(kyb_output: KYBInvestigationOutput,
              ahu_data: dict, ppatk_summary: dict,
              sipp_cases: list, osint_result: dict) -> CriticFeedback:
    """
    AI Critic: Validasi guardrails dan konsistensi skor.

    Calibrated per FATF RBA, POJK 8/2023, PPATK NRA 2023.
    """
    print(f"\n   🕵️ AI Critic: Validasi guardrails...")

    kyb_json = kyb_output.model_dump_json(indent=2)

    prompt = f"""
### PERSONA
Anda adalah Quality Assurance Auditor untuk KYB Intelligence Report.
Tugas Anda: memvalidasi bahwa laporan KYB di bawah ini memenuhi SEMUA guardrails regulasi.

### KYB REPORT YANG AKAN DIEVALUASI
{kyb_json}

### DATA MENTAH (GROUND TRUTH)
AHU: {json.dumps(ahu_data, ensure_ascii=False)[:3000]}
PPATK: {json.dumps(ppatk_summary, ensure_ascii=False)[:2000]}
SIPP: {json.dumps(sipp_cases, ensure_ascii=False)[:2000]}
OSINT: {json.dumps(osint_result, ensure_ascii=False)[:2000]}

### CHECKLIST GUARDRAILS (Periksa SEMUA)

1. ✅ HARUS ada TEPAT 4 intelligence_data dimensi:
   - Corporate & Industry Profiling (Ownership_and_Industry_Risk)
   - AML & APU PPT (AML_Risk)
   - Legal & Litigation (Legal_Risk)
   - Adverse Media & OSINT (Reputation_Risk)

2. ✅ risk_contamination_score HARUS = aml_risk + legal_risk + reputation_risk + ownership_risk
   (Hitung manual dan bandingkan)

3. ✅ overall_risk_level HARUS sesuai skor:
   - 1-25 = LOW
   - 26-50 = MODERATE
   - 51-75 = MODERATE-HIGH
   - 76-100 = HIGH

4. ✅ Jika PPATK has_active_sanctions=true → aml_risk WAJIB >= 40

5. ✅ Setiap pemegang saham korporasi (nama mengandung "PT" atau "CV") WAJIB ada di spider_web_analysis
   dengan risk_flag = CORPORATE_UBO

6. ✅ total_contamination_paths = len(problematic_entities_connected)

7. ✅ Jika action BUKAN APPROVE → required_documents TIDAK BOLEH kosong

8. ✅ Mapping action harus benar:
   - LOW → APPROVE
   - MODERATE → APPROVE_WITH_MONITOR
   - MODERATE-HIGH → REQUIRE_EDD
   - HIGH → ESCALATE_FOR_EDD

9. ✅ scoring_reasoning TIDAK BOLEH kosong — harus menjelaskan logika penilaian

10. ✅ Status TERTUTUP BUKAN faktor risiko — jika digunakan sebagai risiko, TOLAK

11. ✅ company_profile harus terisi lengkap dari data AHU, dan business_description harus berisi 2-3 paragraf narasi bisnis.

12. ✅ company_goals harus berisi semua KBLI dari companyGoals AHU

13. ✅ shareholders_ubo harus berisi SEMUA pemegang saham sesuai data sumber

14. ✅ risk_mitigation TIDAK BOLEH kosong jika action bukan APPROVE

### FORMAT OUTPUT (JSON SCHEMA)
Output HARUS 100% valid JSON sesuai dengan skema berikut:
{json.dumps(CriticFeedback.model_json_schema(), indent=2)}

### OUTPUT
- Jika SEMUA guardrails terpenuhi: is_valid=true, feedback="Laporan memenuhi semua guardrails."
- Jika ADA yang gagal: is_valid=false, feedback=deskripsi detail masalah, missing_fields=list field bermasalah

PENTING UNTUK LIMITASI TOKEN: Jangan berpikir/beralasan terlalu panjang. Tuliskan output secara PADAT dan SINGKAT agar tidak terpotong (truncated)!
"""

    for attempt in range(3):
        try:
            response = client.messages.create(
                model=COMPLEX_REASONING_MODEL,
                max_tokens=8192,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            raw_text = extract_text_from_response(response)
            
            if getattr(response, "stop_reason", None) == "max_tokens":
                raise ValueError("AI Critic truncated (max_tokens).")

            import re
            raw_text = re.sub(r'^```(?:json)?\s*', '', raw_text.strip())
            raw_text = re.sub(r'\s*```$', '', raw_text)
            fb = CriticFeedback.model_validate_json(raw_text)

            if fb.is_valid:
                print("   ✅ Report LULUS validasi guardrails!")
            else:
                print(f"   ❌ Report DITOLAK: {fb.feedback[:120]}...")
            return fb

        except Exception as e:
            print(f"   [!] AI Critic Retry ({attempt+1}/3): {e}")
            if attempt < 2:
                time.sleep(3)

    raise RuntimeError("AI Critic gagal setelah 3 percobaan.")


# ═══════════════════════════════════════════════════════════════════════════════
# Fusion Pipeline (Phase 4 orchestrator)
# ═══════════════════════════════════════════════════════════════════════════════

def run_fusion(ahu_data: dict, ppatk_summary: dict,
               sipp_cases: list, osint_result: dict,
               start_time_ms: int = 0,
               max_revisions: int = 3) -> KYBInvestigationOutput:
    """
    Phase 4 Orchestrator: AI Researcher + AI Critic loop.

    Runs researcher → critic → (revise if needed) loop up to max_revisions.
    """
    print("\n" + "=" * 62)
    print("🧠  PHASE 4: AGENTIC FUSION & RISK SCORING")
    print("=" * 62)

    revision_feedback = ""
    missing_fields = []

    for revision in range(max_revisions + 1):
        if revision > 0:
            print(f"\n   🔄 Revisi ke-{revision}...")

        # AI Researcher
        kyb_output = ai_researcher(
            ahu_data=ahu_data,
            ppatk_summary=ppatk_summary,
            sipp_cases=sipp_cases,
            osint_result=osint_result,
            start_time_ms=start_time_ms,
            revision_feedback=revision_feedback,
            missing_fields=missing_fields,
        )

        # AI Critic
        critic_fb = ai_critic(
            kyb_output=kyb_output,
            ahu_data=ahu_data,
            ppatk_summary=ppatk_summary,
            sipp_cases=sipp_cases,
            osint_result=osint_result,
        )

        if critic_fb.is_valid:
            return kyb_output

        revision_feedback = critic_fb.feedback
        missing_fields = critic_fb.missing_fields

    print(f"\n   ⚠️ Max revisions ({max_revisions}) reached. Menggunakan output terakhir.")
    return kyb_output
