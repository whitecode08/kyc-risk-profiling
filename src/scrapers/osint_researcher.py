"""
OSINT Researcher — Internet Checking (Corporate & UBO)
========================================================
Phase 3 dari KYB Pipeline:
1. Corporate OSINT: Search nama perusahaan via Google Custom Search / Grounding
2. UBO OSINT: Loop Top 5 Pemegang Saham — search per individu
3. AI Summarization: LLM merangkum sentimen, afiliasi, kasus hukum
4. Simpan ke data/output/internet_osint/<company>_full_osint.json
"""

import json
import time
from pathlib import Path

from google import genai
from google.genai import types

from src.config import (
    GEMINI_API_KEY, HEAVY_IO_MODEL,
    OUTPUT_DIR
)

client = genai.Client(api_key=GEMINI_API_KEY)

OSINT_OUTPUT_DIR = OUTPUT_DIR / "internet_osint"


# ─── Corporate OSINT ─────────────────────────────────────────────────────────

def _search_entity(entity_name: str, context: str = "") -> str:
    """
    Lakukan internet search + AI summarization untuk satu entitas
    menggunakan Gemini Google Search Grounding.

    Returns:
        Raw search summary text
    """
    prompt = f"""
Anda adalah analis KYB/AML senior. Lakukan riset internet mendalam untuk entitas berikut.

TARGET: {entity_name}
{f"KONTEKS: {context}" if context else ""}

INSTRUKSI:
1. Cari berita negatif: penipuan, fraud, skandal, korupsi, pelanggaran hukum
2. Cek daftar sanksi: OFAC SDN, UN Security Council, EU Sanctions, PPATK DTTOT
3. Cek PEP (Politically Exposed Person): pejabat publik, politisi, TNI/Polri
4. Verifikasi legitimasi bisnis (jika entitas korporasi)

Berikan ringkasan komprehensif. Jika TIDAK ditemukan informasi negatif,
nyatakan eksplisit bahwa entitas bersih.
"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=HEAVY_IO_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    temperature=0.1,
                ),
            )
            return response.text
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
            else:
                print(f"      ⚠️ Search gagal untuk {entity_name}: {e}")
                return f"Internet research tidak tersedia untuk {entity_name} (API error)"


def _parse_osint_results(raw_summaries: dict, company_name: str) -> dict:
    """
    Parse dan struktur semua hasil OSINT menjadi JSON terstruktur.

    Returns:
        Dict dengan adverse_media, sanctions, pep_flags, dll.
    """
    combined_text = "\n\n".join(
        f"=== {entity} ===\n{summary}"
        for entity, summary in raw_summaries.items()
    )

    parse_prompt = f"""
Analisis hasil riset internet berikut dan ekstrak temuan ke JSON terstruktur.

=== HASIL RISET ===
{combined_text[:6000]}

=== TARGET ===
Perusahaan: {company_name}

=== OUTPUT FORMAT ===
{{
    "adverse_media": [
        {{
            "entity_name": "nama",
            "headline": "judul",
            "summary": "ringkasan",
            "source": "sumber",
            "severity": "Low/Medium/High",
            "relevance_score": 0.0
        }}
    ],
    "sanctions_screening": [
        {{
            "entity_name": "nama",
            "is_sanctioned": false,
            "matches_found": [],
            "screening_notes": "catatan"
        }}
    ],
    "pep_flags": [
        {{
            "name": "nama",
            "is_pep": false,
            "pep_category": "",
            "details": ""
        }}
    ],
    "business_legitimacy_notes": "catatan verifikasi bisnis",
    "overall_internet_risk": "Clean/Flag for Review/High Risk",
    "sentiment_score": 0.0
}}

Jika TIDAK ada temuan negatif, set arrays kosong dan overall_internet_risk = "Clean".
"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=HEAVY_IO_MODEL,
                contents=parse_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            return json.loads(response.text)
        except Exception as e:
            if attempt < 2:
                time.sleep(2)

    return {
        "adverse_media": [],
        "sanctions_screening": [],
        "pep_flags": [],
        "business_legitimacy_notes": "Parsing gagal",
        "overall_internet_risk": "Clean",
        "sentiment_score": 0.0,
    }


# ─── Main Pipeline Function ─────────────────────────────────────────────────

def run_osint_research(company_name: str, top5_ubo: list,
                       kbli_codes: list = None) -> dict:
    """
    Phase 3: Internet Checking (OSINT) — Corporate & UBO.

    Framework: "Lakukan perulangan (loop) untuk Top 5 Pemegang Saham.
    Lakukan search untuk masing-masing nama individu/korporasi tersebut."

    Args:
        company_name: Nama perusahaan
        top5_ubo: List of dict Top 5 UBO (dari data_ingestion.extract_top5_ubo)
        kbli_codes: List kode KBLI (opsional, untuk konteks)

    Returns:
        Dict hasil OSINT terstruktur (saved + returned)
    """
    print(f"\n   🌐 OSINT: Memulai riset internet...")

    raw_summaries = {}

    # 1. Corporate OSINT
    print(f"      🏢 Corporate OSINT: {company_name}")
    kbli_context = f"KBLI: {', '.join(kbli_codes[:5])}" if kbli_codes else ""
    raw_summaries[company_name] = _search_entity(
        company_name,
        context=f"Perusahaan Indonesia. {kbli_context}"
    )

    # 2. UBO OSINT — loop per individu
    for ubo in top5_ubo:
        name = ubo.get("name", "")
        if not name:
            continue

        entity_type = "Korporasi" if ubo.get("is_corporate") else "Individu"
        position = ubo.get("position", "-")
        pct = ubo.get("percentage", 0)

        print(f"      👤 UBO OSINT: {name} ({entity_type}, {pct}%, {position})")
        raw_summaries[name] = _search_entity(
            name,
            context=f"{entity_type}, pemegang saham {company_name} ({pct}%, jabatan: {position})"
        )
        time.sleep(1)  # Rate limiting

    # 3. AI Summarization — parse all results
    print(f"      🔄 Menganalisis dan menyusun temuan...")
    parsed_result = _parse_osint_results(raw_summaries, company_name)

    # Add raw summaries for reference
    parsed_result["raw_summaries"] = {
        k: v[:1000] for k, v in raw_summaries.items()  # Truncate for storage
    }
    parsed_result["entities_searched"] = list(raw_summaries.keys())

    # 4. Save to output
    safe_name = company_name.replace(" ", "_").replace("/", "-")
    output_path = OSINT_OUTPUT_DIR / f"{safe_name}_full_osint.json"
    OSINT_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(parsed_result, f, indent=2, ensure_ascii=False)

    # Print summary
    n_adverse = len(parsed_result.get("adverse_media", []))
    has_sanctions = any(s.get("is_sanctioned") for s in parsed_result.get("sanctions_screening", []))
    has_pep = any(p.get("is_pep") for p in parsed_result.get("pep_flags", []))
    overall = parsed_result.get("overall_internet_risk", "Clean")

    print(f"   💾 OSINT: Disimpan → {output_path}")
    print(f"   📊 Adverse Media: {n_adverse} temuan | "
          f"Sanctions: {'TERDETEKSI' if has_sanctions else 'Bersih'} | "
          f"PEP: {'TERDETEKSI' if has_pep else 'Nihil'} | "
          f"Risk: {overall}")

    return parsed_result
