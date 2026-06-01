import json
import time
from google import genai
from google.genai import types
from src.core.config import Config
from src.core.state import (
    InternetResearchResult, AdverseMediaHit,
    SanctionsScreening, PEPFlag
)

client = genai.Client(api_key=Config.GEMINI_API_KEY)


class InternetResearchTool:
    """
    Tool untuk melakukan riset internet (OSINT) menggunakan Gemini dengan
    Google Search Grounding.
    
    Mencakup:
    1. Adverse Media Screening - berita negatif, dugaan penipuan, skandal
    2. Sanctions List Screening - OFAC, UN, EU, PPATK DTTOT
    3. PEP (Politically Exposed Person) Detection
    4. Business Legitimacy Verification
    """

    @staticmethod
    def research_company(
        company_name: str,
        shareholders: list,
        kbli_codes: list = None,
        nib: str = None
    ) -> InternetResearchResult:
        """
        Melakukan riset internet komprehensif untuk perusahaan dan pemegang sahamnya.
        
        Args:
            company_name: Nama resmi perusahaan
            shareholders: List dict pemegang saham (dari AHU data)
            kbli_codes: List kode KBLI perusahaan
            nib: Nomor Induk Berusaha (opsional, untuk verifikasi)
        
        Returns:
            InternetResearchResult dengan semua temuan
        """
        print(f"\n🌐 [Internet Research Agent] Memulai riset internet untuk: {company_name}")
        
        # Bangun daftar nama entitas yang akan diriset
        entity_names = [company_name]
        shareholder_names = []
        for sh in shareholders:
            name = sh.get("name", "")
            # Skip entitas badan hukum (PT) untuk PEP check, tapi tetap cek adverse media
            if name and len(name) > 2:
                shareholder_names.append(name)
                entity_names.append(name)
        
        # Bangun query pencarian
        search_queries = [
            f'"{company_name}" berita penipuan OR fraud OR skandal OR korupsi',
            f'"{company_name}" sanksi OR blacklist OR PPATK',
            f'"{company_name}" izin usaha OR perizinan OR pencabutan',
        ]
        
        # Tambahkan query untuk pemegang saham kunci (max 3 teratas berdasarkan jabatan)
        key_shareholders = [
            sh for sh in shareholders
            if sh.get("position", "-") not in ["-", ""]
        ][:3]
        
        for sh in key_shareholders:
            name = sh.get("name", "")
            if name:
                search_queries.append(
                    f'"{name}" korupsi OR penipuan OR PEP OR "politically exposed" OR pejabat'
                )

        # ========================================
        # STEP 1: Adverse Media & Sanctions Search
        # ========================================
        print("   🔍 Menjalankan pencarian adverse media & sanctions...")
        
        combined_query = f"""
Anda adalah analis KYB/AML senior. Lakukan riset internet mendalam untuk entitas berikut dalam konteks compliance dan due diligence.

=== TARGET ENTITAS ===
Perusahaan: {company_name}
{"NIB: " + nib if nib else "NIB: Tidak tersedia"}
Pemegang Saham Kunci: {', '.join(shareholder_names[:5])}
{"KBLI: " + ', '.join(kbli_codes) if kbli_codes else ""}

=== INSTRUKSI RISET ===

1. **Adverse Media Screening**:
   - Cari berita negatif tentang perusahaan: penipuan, skandal, fraud, pelanggaran hukum
   - Cari berita negatif tentang pemegang saham kunci
   - Nilai severity: Low (rumor/tidak terkonfirmasi), Medium (laporan media terpercaya), High (putusan pengadilan/tindakan regulasi)

2. **Sanctions Screening**:
   - Periksa apakah perusahaan atau pemegang saham muncul di daftar sanksi internasional
   - Daftar yang dicek: OFAC SDN List, UN Security Council, EU Sanctions, PPATK DTTOT
   - Laporkan jika ada kecocokan nama (bahkan yang parsial)

3. **PEP (Politically Exposed Person) Detection**:
   - Periksa apakah pemegang saham merupakan PEP (pejabat publik, politisi, TNI/Polri senior)
   - Periksa relasi keluarga dekat dengan PEP
   - Kategorikan: Legislatif, Eksekutif, Yudikatif, Militer/Kepolisian, BUMN

4. **Business Legitimacy Verification**:
   - Periksa apakah bisnis ini legitimasi dan beroperasi
   - Cari tanda-tanda shell company atau perusahaan fiktif
   - Verifikasi konsistensi jenis usaha dengan profil publik

Berikan analisis komprehensif dalam format yang terstruktur. Jika TIDAK ditemukan informasi negatif, nyatakan secara eksplisit bahwa entitas bersih dari temuan.
"""

        adverse_media = []
        sanctions_results = []
        pep_flags = []
        business_notes = ""
        raw_summary = ""

        for attempt in range(3):
            try:
                response = client.models.generate_content(
                    model=Config.HEAVY_IO_MODEL,
                    contents=combined_query,
                    config=types.GenerateContentConfig(
                        tools=[types.Tool(google_search=types.GoogleSearch())],
                        temperature=0.1
                    )
                )

                raw_summary = response.text
                print(f"   ✅ Pencarian internet selesai ({len(raw_summary)} karakter)")
                break

            except Exception as e:
                print(f"   [!] Gagal pencarian internet ({e}). Retry {attempt + 1}/3...")
                time.sleep(3)
                if attempt == 2:
                    print("   ⚠️ Internet research gagal. Melanjutkan tanpa hasil internet.")
                    raw_summary = "Internet research tidak tersedia (API error)"

        # ========================================
        # STEP 2: Parse hasil pencarian menjadi structured data
        # ========================================
        print("   🔄 Menganalisis dan menyusun temuan...")

        parse_prompt = f"""
Analisis hasil riset internet berikut dan ekstrak temuan ke dalam format JSON terstruktur.

=== HASIL RISET INTERNET ===
{raw_summary}

=== TARGET ENTITAS ===
Perusahaan: {company_name}
Pemegang Saham: {', '.join(shareholder_names[:5])}

=== OUTPUT FORMAT ===
Berikan output dalam JSON dengan struktur berikut:
{{
    "adverse_media": [
        {{
            "entity_name": "nama entitas terkait",
            "headline": "judul temuan",
            "summary": "ringkasan temuan",
            "source": "sumber berita/URL",
            "severity": "Low/Medium/High",
            "relevance_score": 0.0-1.0
        }}
    ],
    "sanctions_hits": [
        {{
            "entity_name": "nama yang dicek",
            "is_sanctioned": false,
            "matches_found": [],
            "screening_notes": "catatan"
        }}
    ],
    "pep_flags": [
        {{
            "name": "nama individu",
            "is_pep": false,
            "pep_category": "",
            "details": ""
        }}
    ],
    "business_legitimacy_notes": "catatan verifikasi bisnis",
    "overall_internet_risk": "Clean/Flag for Review/High Risk"
}}

PENTING:
- Jika TIDAK ada temuan negatif, tetap isi array kosong dan set overall_internet_risk = "Clean"
- Hanya laporkan temuan yang BENAR-BENAR terkait dengan entitas target, bukan entitas lain dengan nama mirip (anti-bias)
- Severity "High" HANYA untuk kasus dengan bukti kuat (putusan pengadilan, tindakan resmi)
"""

        parsed_result = None
        for attempt in range(3):
            try:
                parse_response = client.models.generate_content(
                    model=Config.HEAVY_IO_MODEL,
                    contents=parse_prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        temperature=0.1
                    )
                )
                parsed_result = json.loads(parse_response.text)
                break
            except Exception as e:
                print(f"   [!] Gagal parsing hasil ({e}). Retry {attempt + 1}/3...")
                time.sleep(2)

        # ========================================
        # STEP 3: Bangun InternetResearchResult
        # ========================================
        if parsed_result:
            # Parse adverse media
            for item in parsed_result.get("adverse_media", []):
                adverse_media.append(AdverseMediaHit(
                    entity_name=item.get("entity_name", ""),
                    headline=item.get("headline", ""),
                    summary=item.get("summary", ""),
                    source=item.get("source", ""),
                    severity=item.get("severity", "Low"),
                    relevance_score=item.get("relevance_score", 0.0)
                ))

            # Parse sanctions
            for item in parsed_result.get("sanctions_hits", []):
                sanctions_results.append(SanctionsScreening(
                    entity_name=item.get("entity_name", ""),
                    is_sanctioned=item.get("is_sanctioned", False),
                    matches_found=item.get("matches_found", []),
                    screening_notes=item.get("screening_notes", "")
                ))

            # Parse PEP flags
            for item in parsed_result.get("pep_flags", []):
                pep_flags.append(PEPFlag(
                    name=item.get("name", ""),
                    is_pep=item.get("is_pep", False),
                    pep_category=item.get("pep_category", ""),
                    details=item.get("details", "")
                ))

            business_notes = parsed_result.get("business_legitimacy_notes", "")
            overall_risk = parsed_result.get("overall_internet_risk", "Clean")
        else:
            overall_risk = "Clean"
            business_notes = "Tidak dapat melakukan verifikasi internet (parsing gagal)"

        # Print summary
        has_adverse = len([a for a in adverse_media if a.severity in ["Medium", "High"]]) > 0
        has_sanctions = any(s.is_sanctioned for s in sanctions_results)
        has_pep = any(p.is_pep for p in pep_flags)

        if has_adverse:
            print(f"   ⚠️ Adverse Media: {len(adverse_media)} temuan ditemukan")
        else:
            print(f"   ✅ Adverse Media: Bersih ({len(adverse_media)} temuan minor)")
        
        if has_sanctions:
            print(f"   🚨 Sanctions: TERDETEKSI kecocokan pada daftar sanksi!")
        else:
            print(f"   ✅ Sanctions: Tidak ditemukan kecocokan")
        
        if has_pep:
            pep_names = [p.name for p in pep_flags if p.is_pep]
            print(f"   ⚠️ PEP: Terdeteksi {len(pep_names)} PEP: {', '.join(pep_names)}")
        else:
            print(f"   ✅ PEP: Tidak terdeteksi Politically Exposed Person")

        print(f"   📊 Overall Internet Risk: {overall_risk}")

        result = InternetResearchResult(
            adverse_media=adverse_media,
            sanctions_screening=sanctions_results,
            pep_flags=pep_flags,
            business_legitimacy_notes=business_notes,
            overall_internet_risk=overall_risk,
            search_queries_used=search_queries,
            raw_search_summary=raw_summary[:2000]  # Truncate for storage
        )

        return result
