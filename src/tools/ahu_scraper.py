import json
from pathlib import Path
from google import genai
from google.genai import types
from src.core.config import Config
from src.tools.scraper import (
    init_db, load_ahu_from_json, load_ahu_from_csv,
    search_ahu_db, search_ahu_by_nib, get_all_ahu_companies
)


class AHUScraperTool:
    """
    Tool untuk mengekstrak data profil perusahaan dari Ditjen AHU.

    Data bersumber dari internal DB (SQLite) yang telah diisi dari:
    - File JSON (format sesuai skema AHU seperti examples/ANEKA BINTANG GADING.json)
    - File CSV (flat export dari AHU)

    Mendukung empat mode:
    1. DB lookup by nama  - cari profil dari internal DB berdasarkan nama perusahaan
    2. DB lookup by NIB   - cari profil dari internal DB berdasarkan NIB
    3. PDF extraction     - ekstraksi data dari file PDF menggunakan Gemini Flash
    4. JSON/CSV loading   - muat langsung dari file (sekaligus simpan ke DB)
    """

    @staticmethod
    def _db_path() -> str:
        return Config.DB_PATH

    # ──────────────────────────────────────────────────────────────────────────
    # Lookup Methods (query internal DB)
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_company_profile(company_name: str) -> dict:
        """
        Mengambil profil perusahaan dari internal DB berdasarkan nama.

        Args:
            company_name: Nama perusahaan (partial match, case-insensitive)

        Returns:
            dict profil perusahaan, atau dict dengan key 'error' jika tidak ditemukan
        """
        result = search_ahu_db(company_name, db_path=AHUScraperTool._db_path())
        if result:
            return result
        return {"error": f"Data AHU tidak ditemukan untuk: '{company_name}'. "
                         f"Pastikan data sudah diimport via load_from_json() atau load_from_csv()."}

    @staticmethod
    def get_company_by_nib(nib: str) -> dict:
        """
        Mengambil profil perusahaan dari internal DB berdasarkan NIB.

        Args:
            nib: Nomor Induk Berusaha

        Returns:
            dict profil perusahaan, atau dict dengan key 'error' jika tidak ditemukan
        """
        result = search_ahu_by_nib(nib, db_path=AHUScraperTool._db_path())
        if result:
            return result
        return {"error": f"NIB '{nib}' tidak ditemukan dalam database. Silakan import data AHU terlebih dahulu."}

    @staticmethod
    def lookup(company_name: str = None, nib: str = None) -> dict:
        """
        Unified lookup - coba NIB dulu, fallback ke nama perusahaan.

        Args:
            company_name: Nama perusahaan (opsional)
            nib:          Nomor Induk Berusaha (opsional)

        Returns:
            dict profil perusahaan
        """
        # Prioritas 1: NIB lookup
        if nib:
            result = AHUScraperTool.get_company_by_nib(nib)
            if "error" not in result:
                return result

        # Prioritas 2: Nama perusahaan
        if company_name:
            result = AHUScraperTool.get_company_profile(company_name)
            if "error" not in result:
                return result

        return {"error": f"Data tidak ditemukan untuk NIB='{nib}' atau nama='{company_name}'. "
                         f"Silakan import file JSON/CSV AHU terlebih dahulu, atau upload PDF/JSON manual."}

    # ──────────────────────────────────────────────────────────────────────────
    # File Loading Methods (juga menyimpan ke DB)
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def load_from_json(json_path: str) -> dict:
        """
        Muat data profil perusahaan dari file JSON AHU.
        Data otomatis disimpan ke internal DB untuk lookup berikutnya.

        Args:
            json_path: Path ke file JSON (format: examples/ANEKA BINTANG GADING.json)

        Returns:
            dict profil perusahaan
        """
        try:
            data = load_ahu_from_json(json_path, db_path=AHUScraperTool._db_path())
            company_name = data.get("company", {}).get("name", json_path)
            print(f"   ✅ Data AHU JSON dimuat dari: {json_path} ({company_name})")
            return data
        except FileNotFoundError:
            return {"error": f"File tidak ditemukan: {json_path}"}
        except ValueError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"Gagal memuat JSON AHU: {str(e)}"}

    @staticmethod
    def load_from_csv(csv_path: str) -> dict:
        """
        Muat data profil perusahaan dari file CSV AHU.
        Data otomatis disimpan ke internal DB.

        Args:
            csv_path: Path ke file CSV

        Returns:
            dict berisi jumlah record yang dimuat: {"loaded": N}
        """
        try:
            count = load_ahu_from_csv(csv_path, db_path=AHUScraperTool._db_path())
            print(f"   ✅ Data AHU CSV dimuat dari: {csv_path} ({count} perusahaan)")
            return {"loaded": count, "source": csv_path}
        except FileNotFoundError:
            return {"error": f"File tidak ditemukan: {csv_path}"}
        except Exception as e:
            return {"error": f"Gagal memuat CSV AHU: {str(e)}"}

    @staticmethod
    def extract_from_pdf(pdf_path: str) -> dict:
        """
        Mengekstrak data profil perusahaan dari file PDF AHU menggunakan Gemini Flash.
        Hasil ekstraksi otomatis disimpan ke internal DB.

        Args:
            pdf_path: Path ke file PDF

        Returns:
            dict profil perusahaan
        """
        try:
            client = genai.Client(api_key=Config.GEMINI_API_KEY)

            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            # Upload PDF ke Gemini
            uploaded_file = client.files.upload(
                file=pdf_bytes,
                config=types.UploadFileConfig(
                    mime_type="application/pdf",
                    display_name=Path(pdf_path).name
                )
            )

            prompt = """
            Ekstrak SEMUA informasi dari dokumen PDF profil perusahaan Ditjen AHU ini ke dalam format JSON terstruktur.

            Output HARUS dalam format JSON dengan struktur berikut:
            {
                "company": { "name", "shortName", "skNumber", "skDate", "spNumber", "spDate",
                             "companySpNumber", "companySpDate", "type", "timePeriod", "status", "phoneNo", "transactionType" },
                "companyAddress": { "address", "rt", "rw", "postalCode", "ward", "subdistrict", "regency", "province" },
                "companyGoals": [{ "no", "code", "name", "description" }],
                "notary": { "name", "shortAddress", "deedNumber", "deedDate" },
                "baseStock": { "classification", "pricePerShare", "numberOfShares", "grandTotal" },
                "issuedStock": { "classification", "pricePerShare", "numberOfShares", "grandTotal" },
                "paidUpStock": "string",
                "shareholders": [{ "name", "passport", "country", "kitas", "ttl", "position", "address",
                                   "classification", "numberOfShares", "grandTotal" }]
            }

            PENTING:
            - Isi SEMUA field yang bisa ditemukan dari dokumen
            - Untuk field yang tidak ditemukan, gunakan string kosong ""
            - numberOfShares harus berupa string angka tanpa separator (contoh: "500000000")
            - grandTotal dalam format "Rp. X,XXX,XXX"
            """

            response = client.models.generate_content(
                model=Config.HEAVY_IO_MODEL,
                contents=[uploaded_file, prompt],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1
                )
            )

            data = json.loads(response.text)

            # Simpan hasil ekstraksi ke DB
            if "company" in data and data["company"].get("name"):
                try:
                    # Simpan sementara ke file temp, lalu load ke DB
                    import tempfile, os
                    with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                                    delete=False, encoding="utf-8") as tmp:
                        json.dump(data, tmp, ensure_ascii=False)
                        tmp_path = tmp.name
                    load_ahu_from_json(tmp_path, db_path=AHUScraperTool._db_path())
                    os.unlink(tmp_path)
                    print(f"   ✅ Data PDF disimpan ke DB: {data['company']['name']}")
                except Exception as e:
                    print(f"   ⚠️ Gagal simpan ke DB (data masih tersedia): {e}")

            return data
        except Exception as e:
            print(f"   [!] Gagal mengekstrak PDF: {e}")
            return {"error": f"Gagal mengekstrak PDF: {str(e)}"}

    # ──────────────────────────────────────────────────────────────────────────
    # Utility Methods
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_available_companies() -> dict:
        """
        Kembalikan semua perusahaan yang tersedia di internal DB.

        Returns:
            Dict {company_name: nib_or_dash}
        """
        return get_all_ahu_companies(db_path=AHUScraperTool._db_path())

    @staticmethod
    def get_available_nibs() -> dict:
        """
        Backward-compat alias untuk get_available_companies().
        Kembalikan {nib: company_name} untuk perusahaan yang memiliki NIB.
        """
        companies = get_all_ahu_companies(db_path=AHUScraperTool._db_path())
        return {nib: name for name, nib in companies.items() if nib != "-"}