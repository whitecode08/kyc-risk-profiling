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
"""

import json
import time
from datetime import datetime, timezone
from typing import List, Optional, Union

from pydantic import BaseModel, Field
from google import genai
from google.genai import types

from src.config import (
    GEMINI_API_KEY, HEAVY_IO_MODEL, COMPLEX_REASONING_MODEL,
    RISK_WEIGHTS
)

client = genai.Client(api_key=GEMINI_API_KEY)


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic Models — KYB Investigation Output (sesuai ref_output.json)
# ═══════════════════════════════════════════════════════════════════════════════

class IntelligenceDataPoint(BaseModel):
    attribute: str = Field(description="Nama atribut")
    value: Union[str, bool, int, float, List[str], List[dict], dict, type(None)] = Field(description="Nilai atribut")


class IntelligenceDimension(BaseModel):
    dimension: str = Field(description="Nama dimensi analisis")
    source_system: str = Field(description="Sistem sumber data")
    data_points: List[IntelligenceDataPoint] = Field(default_factory=list)
    finding: str = Field(description="Narasi temuan dimensi")
    risk_weight: int = Field(description="Bobot kontribusi (0-50)")
    category: str = Field(description="Kategori risiko")


class ScoreBreakdown(BaseModel):
    aml_risk: int = Field(default=0, description="Skor AML (0-50)")
    legal_risk: int = Field(default=0, description="Skor Legal (0-20)")
    reputation_risk: int = Field(default=0, description="Skor Reputation (0-20)")
    ownership_risk: int = Field(default=0, description="Skor Ownership (0-25)")


class AIRiskScoring(BaseModel):
    overall_risk_level: str = Field(description="LOW/MODERATE/MODERATE-HIGH/HIGH")
    risk_contamination_score: int = Field(description="Skor 0-100")
    score_breakdown: ScoreBreakdown = Field(default_factory=ScoreBreakdown)


class ProblematicEntity(BaseModel):
    entity_name: str
    connection_type: str = Field(description="Directorship/Shareholder/Beneficiary/Associate")
    risk_flag: str = Field(description="PPATK_STR/PPATK_DTTOT/SIPP_LITIGATION/PEP/ADVERSE_MEDIA/CORPORATE_UBO")


class SpiderWebAnalysis(BaseModel):
    total_contamination_paths: int = Field(default=0)
    problematic_entities_connected: List[ProblematicEntity] = Field(default_factory=list)


class AIRecommendation(BaseModel):
    action: str = Field(description="APPROVE/APPROVE_WITH_MONITOR/REQUIRE_EDD/ESCALATE_FOR_EDD/REJECT")
    narrative: str = Field(description="Narasi Bahasa Indonesia")
    required_documents: List[str] = Field(default_factory=list)


class CorporateEntity(BaseModel):
    name: str
    sk_number: str = ""
    company_type: str = ""


class InvestigationMetadata(BaseModel):
    investigation_id: str
    timestamp: str
    processing_time_ms: int = 0
    status: str = "COMPLETED"


class KYBInvestigationOutput(BaseModel):
    """Model output final KYB Investigation — sesuai ref_output.json."""
    metadata: InvestigationMetadata
    corporate_entity: CorporateEntity
    ai_risk_scoring: AIRiskScoring
    intelligence_data: List[IntelligenceDimension] = Field(default_factory=list)
    spider_web_analysis: SpiderWebAnalysis = Field(default_factory=SpiderWebAnalysis)
    ai_recommendation: AIRecommendation


class CriticFeedback(BaseModel):
    """Feedback dari AI Critic."""
    is_valid: bool = Field(description="True jika memenuhi guardrails")
    feedback: str = Field(description="Detail kritik/koreksi")
    missing_fields: List[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# AI Researcher
# ═══════════════════════════════════════════════════════════════════════════════

def ai_researcher(ahu_data: dict, ppatk_summary: dict,
                  sipp_cases: list, osint_result: dict,
                  start_time_ms: int = 0,
                  revision_feedback: str = "",
                  missing_fields: list = None) -> KYBInvestigationOutput:
    """
    AI Researcher: Membaca 4 sumber JSON sekaligus dan merangkum
    narasi komprehensif → KYBInvestigationOutput.

    Framework: "AI Researcher bertugas membaca 4 file JSON sekaligus
    (AHU, PPATK, SIPP Scraped, OSINT). AI ini merangkum narasi
    komprehensif terkait kondisi nasabah."
    """
    print(f"\n   🔬 AI Researcher: Menyusun narasi dari 4 sumber data...")

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

    prompt = f"""
Anda adalah analis KYB (Know Your Business) senior di divisi Compliance & AML.
Analisis data perusahaan dari 4 sumber berikut dan hasilkan KYB Intelligence Report.

=== 1. DATA PROFIL PERUSAHAAN (Ditjen AHU) ===
{ahu_context}

=== 2. SCREENING PPATK DTTOT ===
{ppatk_context}

=== 3. DATA LITIGASI (SIPP MA) ===
{sipp_context}

=== 4. HASIL RISET INTERNET (OSINT) ===
{osint_context}

=== KONFIGURASI BOBOT RISIKO ===
- Ownership_and_Industry_Risk: max {dim_weights.get('Ownership_and_Industry_Risk', {}).get('max_score', 25)}
- AML_Risk: max {dim_weights.get('AML_Risk', {}).get('max_score', 50)}
- Legal_Risk: max {dim_weights.get('Legal_Risk', {}).get('max_score', 20)}
- Reputation_Risk: max {dim_weights.get('Reputation_Risk', {}).get('max_score', 20)}

Score adders:
- UBO >=25%: +{score_adders.get('ubo_above_threshold_25pct', 15)}
- KBLI High Risk ({', '.join(kbli_high_risk[:5])}...): +{score_adders.get('high_risk_kbli_detected', 15)}
- Corporate shareholder opaque: +{score_adders.get('corporate_shareholder_opaque', 10)}
- STR history: +{score_adders.get('str_history_detected', 20)}
- DTTOT aktif: +{score_adders.get('dttot_active_sanction', 40)}
- Litigasi perdata: +{score_adders.get('active_litigation_perdata', 10)}
- Adverse media High: +{score_adders.get('adverse_media_high_severity', 20)}
- PEP: +{score_adders.get('pep_detected', 15)}

=== OUTPUT JSON (HARUS PERSIS) ===
{{
  "metadata": {{
    "investigation_id": "KYB-YYYYMMDD-NNN",
    "timestamp": "ISO8601 UTC",
    "processing_time_ms": 0,
    "status": "COMPLETED"
  }},
  "corporate_entity": {{
    "name": "NAMA PERUSAHAAN",
    "sk_number": "nomor SK",
    "company_type": "PMDN/PMA"
  }},
  "ai_risk_scoring": {{
    "overall_risk_level": "LOW|MODERATE|MODERATE-HIGH|HIGH",
    "risk_contamination_score": 0,
    "score_breakdown": {{
      "aml_risk": 0,
      "legal_risk": 0,
      "reputation_risk": 0,
      "ownership_risk": 0
    }}
  }},
  "intelligence_data": [
    {{
      "dimension": "Corporate & Industry Profiling",
      "source_system": "API_AHU_KEMENKUMHAM",
      "data_points": [{{"attribute": "KBLI", "value": ["kode - nama"]}}, ...],
      "finding": "narasi temuan",
      "risk_weight": 0,
      "category": "Ownership_and_Industry_Risk"
    }},
    {{
      "dimension": "AML & APU PPT",
      "source_system": "PPATK_WATCHLIST_DB",
      "data_points": [{{"attribute": "DTTOT_Match", "value": false}}, ...],
      "finding": "narasi",
      "risk_weight": 0,
      "category": "AML_Risk"
    }},
    {{
      "dimension": "Legal & Litigation",
      "source_system": "SIPP_MAHKAMAH_AGUNG_SCRAPER",
      "data_points": [{{"attribute": "Active_Cases", "value": "..."}}],
      "finding": "narasi",
      "risk_weight": 0,
      "category": "Legal_Risk"
    }},
    {{
      "dimension": "Adverse Media & OSINT",
      "source_system": "GOOGLE_CUSTOM_SEARCH_API",
      "data_points": [{{"attribute": "Negative_News_Count", "value": 0}}],
      "finding": "narasi",
      "risk_weight": 0,
      "category": "Reputation_Risk"
    }}
  ],
  "spider_web_analysis": {{
    "total_contamination_paths": 0,
    "problematic_entities_connected": [
      {{"entity_name": "nama", "connection_type": "...", "risk_flag": "..."}}
    ]
  }},
  "ai_recommendation": {{
    "action": "APPROVE|APPROVE_WITH_MONITOR|REQUIRE_EDD|ESCALATE_FOR_EDD|REJECT",
    "narrative": "narasi Bahasa Indonesia",
    "required_documents": ["dokumen"]
  }}
}}

=== ATURAN PENTING ===
1. UBO: hitung persentase = (numberOfShares / {paid_up_capital}) * 100
2. Status TERTUTUP = PT Tertutup (bukan Tbk), BUKAN tutup. JANGAN jadikan risiko.
3. PPATK: jika has_active_sanctions=true → AML risk_weight WAJIB >= 40
4. risk_contamination_score = sum(score_breakdown)
5. 1-25=LOW, 26-50=MODERATE, 51-75=MODERATE-HIGH, 76-100=HIGH
6. Pemegang saham PT (korporasi) → WAJIB spider_web dengan flag CORPORATE_UBO
7. LOW→APPROVE, MODERATE→APPROVE_WITH_MONITOR, MODERATE-HIGH→REQUIRE_EDD, HIGH→ESCALATE_FOR_EDD

{f"CATATAN REVISI: {revision_feedback}" if revision_feedback else ""}
{f"FIELD BERMASALAH: {', '.join(missing_fields)}" if missing_fields else ""}
"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=HEAVY_IO_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                ),
            )

            raw = json.loads(response.text)
            elapsed_ms = int(time.time() * 1000) - start_time_ms if start_time_ms else 0

            # Build KYBInvestigationOutput
            meta = raw.get("metadata", {})
            corp = raw.get("corporate_entity", {})
            scoring = raw.get("ai_risk_scoring", {})
            bd = scoring.get("score_breakdown", {})
            spider = raw.get("spider_web_analysis", {})
            reco = raw.get("ai_recommendation", {})

            output = KYBInvestigationOutput(
                metadata=InvestigationMetadata(
                    investigation_id=meta.get("investigation_id",
                                              f"KYB-{datetime.now().strftime('%Y%m%d')}-001"),
                    timestamp=meta.get("timestamp",
                                       datetime.now(timezone.utc).isoformat()),
                    processing_time_ms=elapsed_ms or meta.get("processing_time_ms", 0),
                    status="COMPLETED",
                ),
                corporate_entity=CorporateEntity(
                    name=corp.get("name",
                                  ahu_data.get("company", {}).get("name", "")),
                    sk_number=corp.get("sk_number",
                                       ahu_data.get("company", {}).get("skNumber", "")),
                    company_type=corp.get("company_type",
                                          ahu_data.get("company", {}).get("type", "")),
                ),
                ai_risk_scoring=AIRiskScoring(
                    overall_risk_level=scoring.get("overall_risk_level", "MODERATE"),
                    risk_contamination_score=scoring.get("risk_contamination_score", 0),
                    score_breakdown=ScoreBreakdown(
                        aml_risk=bd.get("aml_risk", 0),
                        legal_risk=bd.get("legal_risk", 0),
                        reputation_risk=bd.get("reputation_risk", 0),
                        ownership_risk=bd.get("ownership_risk", 0),
                    ),
                ),
                intelligence_data=[
                    IntelligenceDimension(
                        dimension=d.get("dimension", ""),
                        source_system=d.get("source_system", ""),
                        data_points=[
                            IntelligenceDataPoint(
                                attribute=dp.get("attribute", ""),
                                value=dp.get("value", ""),
                            )
                            for dp in d.get("data_points", [])
                        ],
                        finding=d.get("finding", ""),
                        risk_weight=d.get("risk_weight", 0),
                        category=d.get("category", ""),
                    )
                    for d in raw.get("intelligence_data", [])
                ],
                spider_web_analysis=SpiderWebAnalysis(
                    total_contamination_paths=spider.get("total_contamination_paths", 0),
                    problematic_entities_connected=[
                        ProblematicEntity(
                            entity_name=e.get("entity_name", ""),
                            connection_type=e.get("connection_type", ""),
                            risk_flag=e.get("risk_flag", ""),
                        )
                        for e in spider.get("problematic_entities_connected", [])
                    ],
                ),
                ai_recommendation=AIRecommendation(
                    action=reco.get("action", "REQUIRE_EDD"),
                    narrative=reco.get("narrative", ""),
                    required_documents=reco.get("required_documents", []),
                ),
            )

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
    AI Critic: Membaca narasi dari Researcher dan membandingkannya
    dengan risk_weights.json. Validasi guardrails dan konsistensi skor.

    Framework: "AI Critic bertugas membaca narasi dari Researcher dan
    membandingkannya dengan risk_weights.json. AI ini menghitung final
    Risk Score secara deterministik dan menjustifikasi skor tersebut."
    """
    print(f"\n   🕵️ AI Critic: Validasi guardrails...")

    kyb_json = kyb_output.model_dump_json(indent=2)

    prompt = f"""
Evaluasi KYB Intelligence Report berikut terhadap data mentah asli.

=== KYB REPORT ===
{kyb_json}

=== DATA MENTAH (GROUND TRUTH) ===
AHU: {json.dumps(ahu_data, ensure_ascii=False)[:3000]}
PPATK: {json.dumps(ppatk_summary, ensure_ascii=False)[:2000]}
SIPP: {json.dumps(sipp_cases, ensure_ascii=False)[:2000]}
OSINT: {json.dumps(osint_result, ensure_ascii=False)[:2000]}

=== GUARDRAILS ===
1. HARUS ada 4 intelligence_data dimensi lengkap
2. risk_contamination_score HARUS = sum(score_breakdown)
3. overall_risk_level: 1-25=LOW, 26-50=MODERATE, 51-75=MODERATE-HIGH, 76-100=HIGH
4. Jika PPATK has_active_sanctions=true → AML risk_weight >= 40
5. Pemegang saham korporasi (PT) → WAJIB spider_web CORPORATE_UBO
6. total_contamination_paths = jumlah problematic_entities_connected
7. LOW→APPROVE, MODERATE→APPROVE_WITH_MONITOR, MODERATE-HIGH→REQUIRE_EDD, HIGH→ESCALATE_FOR_EDD
8. required_documents TIDAK BOLEH kosong jika action bukan APPROVE
9. Status TERTUTUP bukan risiko

JIKA SEMUA OK → is_valid=true. JIKA ADA MASALAH → is_valid=false + feedback.
"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=COMPLEX_REASONING_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CriticFeedback,
                    temperature=0.1,
                ),
            )
            fb = CriticFeedback.model_validate_json(response.text)

            if fb.is_valid:
                print("   ✅ Report LULUS validasi guardrails!")
            else:
                print(f"   ❌ Report DITOLAK: {fb.feedback}")
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
