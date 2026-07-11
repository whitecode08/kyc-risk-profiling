"""
SIPP Scraper — Sistem Informasi Penelusuran Perkara Mahkamah Agung RI
======================================================================
Phase 2 dari KYB Pipeline:
1. Non-AI Scraping: BeautifulSoup untuk search nama perusahaan di portal SIPP
2. AI Structuring: LLM (Gemini) structured output → JSON baku
3. Simpan ke data/output/sipp_scraped/<company>.json
"""

import json
import time
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

from src.config import (
    GEMINI_API_KEY, HEAVY_IO_MODEL,
    OUTPUT_DIR
)
from src.data_ingestion import make_output_filename

client = genai.Client(api_key=GEMINI_API_KEY)

# ─── SIPP Portal Config ──────────────────────────────────────────────────────

COURTS = {
    "surabaya": {
        "name": "PN Niaga Surabaya",
        "base_url": "https://sipp.pn-surabayakota.go.id",
    },
    "jakarta": {
        "name": "PN Niaga Jakarta Pusat",
        "base_url": "https://sipp.pn-jakartapusat.go.id",
    },
    "medan": {
        "name": "PN Niaga Medan",
        "base_url": "https://sipp.pn-medankota.go.id",
    },
    "makassar": {
        "name": "PN Niaga Makassar",
        "base_url": "https://sipp.pn-makassar.go.id",
    },
    "semarang": {
        "name": "PN Niaga Semarang",
        "base_url": "https://sipp.pn-semarangkota.go.id",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
}

SIPP_OUTPUT_DIR = OUTPUT_DIR / "sipp_scraped"


# ─── Non-AI Scraping ─────────────────────────────────────────────────────────

def scrape_sipp_raw(entity_name: str) -> str:
    """
    Scrape raw HTML dari portal SIPP untuk nama entitas.

    Tries all 5 Pengadilan Niaga. Returns concatenated raw text.
    Returns empty string if all fail (e.g. network down, Cloudflare).
    """
    all_text = []

    for court_key, court in COURTS.items():
        try:
            search_url = f"{court['base_url']}/list_perkara/search"
            session = requests.Session()
            session.headers.update(HEADERS)

            resp = session.get(
                search_url,
                params={"search": entity_name},
                timeout=15
            )

            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "lxml")
                table = soup.find("table")
                if table:
                    text = table.get_text(separator="\n", strip=True)
                    all_text.append(f"--- {court['name']} ---\n{text}")

            time.sleep(2)  # Rate limiting

        except Exception as e:
            print(f"      ⚠️ SIPP {court['name']}: {e}")
            continue

    return "\n\n".join(all_text)


# ─── AI Structuring ──────────────────────────────────────────────────────────

def structure_sipp_with_llm(raw_text: str, entity_name: str) -> list:
    """
    Gunakan Gemini untuk mengubah raw SIPP text menjadi structured JSON.

    Framework: "Lempar raw text ke LLM menggunakan Structured Output (Pydantic schema)
    untuk mengubahnya menjadi JSON baku: nomor_perkara, klasifikasi, status."

    Returns:
        List of dict dengan keys: nomor_perkara, klasifikasi, status_perkara,
        pemohon, termohon, court, tanggal_register
    """
    if not raw_text or len(raw_text.strip()) < 20:
        return []

    prompt = f"""
Anda adalah asisten hukum. Ekstrak semua perkara litigasi dari teks SIPP berikut
yang berkaitan dengan entitas "{entity_name}".

=== RAW SIPP TEXT ===
{raw_text[:4000]}

=== OUTPUT FORMAT ===
Kembalikan JSON array dengan format:
[
  {{
    "nomor_perkara": "nomor perkara",
    "court": "nama pengadilan",
    "tanggal_register": "tanggal",
    "klasifikasi": "Kepailitan/PKPU/Perdata/Pidana/dll",
    "pemohon": "nama pemohon",
    "termohon": "nama termohon",
    "status_perkara": "Putus/Proses/Mediasi/dll",
    "lama_proses": "durasi jika ada"
  }}
]

Jika tidak ada perkara yang ditemukan, kembalikan array kosong [].
Hanya sertakan perkara yang BENAR-BENAR terkait dengan "{entity_name}".
"""

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=HEAVY_IO_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            result = json.loads(response.text)
            if isinstance(result, list):
                return result
            return []
        except Exception as e:
            if attempt < 2:
                time.sleep(3)
            else:
                print(f"      ⚠️ LLM structuring gagal: {e}")
                return []


# ─── Main Pipeline Function ─────────────────────────────────────────────────

def run_sipp_scraping(company_name: str, shareholder_names: list = None,
                      db_number: str = "00") -> list:
    """
    Phase 2: SIPP Scraping & Structuring.

    1. Scrape raw text dari portal SIPP (company + shareholders)
    2. LLM structure → JSON
    3. Save ke data/output/sipp_scraped/{db_number}__sipp__{company}.json

    Args:
        company_name: Nama perusahaan
        shareholder_names: List nama pemegang saham/pengurus (opsional)
        db_number: Database number prefix for output naming

    Returns:
        List of dict — semua kasus litigasi terstruktur
    """
    print(f"\n   📋 SIPP: Memeriksa riwayat litigasi...")

    all_cases = []
    entities = [company_name]
    if shareholder_names:
        entities.extend(shareholder_names[:5])  # max 5 shareholders

    for entity in entities:
        if not entity or not entity.strip():
            continue

        print(f"      🔍 Mencari: {entity}")
        raw_text = scrape_sipp_raw(entity)

        if raw_text:
            cases = structure_sipp_with_llm(raw_text, entity)
            if cases:
                # Deduplicate by nomor_perkara
                existing = {c.get("nomor_perkara") for c in all_cases}
                new_cases = [c for c in cases if c.get("nomor_perkara") not in existing]
                all_cases.extend(new_cases)
                print(f"      ⚠️ Ditemukan {len(new_cases)} perkara untuk {entity}")
            else:
                print(f"      ✅ Tidak ada perkara untuk {entity}")
        else:
            print(f"      ℹ️ Portal SIPP tidak dapat diakses untuk {entity}")

    # Save to output
    out_filename = make_output_filename(db_number, "sipp", company_name)
    output_path = SIPP_OUTPUT_DIR / out_filename
    SIPP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "company": company_name,
            "total_cases": len(all_cases),
            "cases": all_cases,
        }, f, indent=2, ensure_ascii=False)

    print(f"   💾 SIPP: {len(all_cases)} kasus disimpan → {output_path}")
    return all_cases


def load_sipp_from_json(json_path: str) -> list:
    """Load data SIPP dari file JSON yang sudah ada."""
    path = Path(json_path)
    if not path.exists():
        print(f"   ⚠️ File SIPP tidak ditemukan: {json_path}")
        return []

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data
    elif isinstance(data, dict) and "cases" in data:
        return data["cases"]
    return [data]
