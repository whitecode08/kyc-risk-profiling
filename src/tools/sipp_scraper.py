"""
SIPP Scraper Tool - Sistem Informasi Penelusuran Perkara Mahkamah Agung RI

Tool ringan yang digunakan oleh pipeline untuk query data litigasi kepailitan/PKPU.
Data diambil dari internal DB (SQLite) yang sudah diisi oleh scraper.py.

Untuk mengisi DB, jalankan scraper.py terlebih dahulu:
    python src/tools/scraper.py --court surabaya
    python src/tools/scraper.py --court all

Atau saat manual upload, gunakan load_from_json() untuk data litigasi custom.
"""

import json
import sqlite3
from pathlib import Path
from src.core.config import Config
from src.tools.scraper import init_db


class SIPPScraperTool:
    """
    Tool untuk memeriksa riwayat litigasi dari SIPP Mahkamah Agung RI.

    Mendukung:
    1. DB lookup  - query dari tabel `perkara` (diisi oleh scraper.py)
    2. JSON load  - muat data litigasi manual dari file JSON (override)
    """

    @staticmethod
    def _db_path() -> str:
        return Config.DB_PATH

    # ──────────────────────────────────────────────────────────────────────────
    # Core Lookup (query tabel perkara di DB)
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def check_litigation(entity_name: str) -> list:
        """
        Periksa riwayat litigasi suatu entitas di DB SIPP.

        Pencarian dilakukan di kolom pemohon DAN termohon (partial match).

        Args:
            entity_name: Nama entitas yang akan dicek (perusahaan atau individu)

        Returns:
            List of dict berisi detail kasus litigasi. List kosong jika tidak ada.
        """
        if not entity_name or not entity_name.strip():
            return []

        try:
            conn = init_db(SIPPScraperTool._db_path())
            q = f"%{entity_name.upper()}%"
            rows = conn.execute("""
                SELECT
                    court,
                    nomor_perkara,
                    tanggal_register,
                    klasifikasi,
                    pemohon,
                    termohon,
                    status_perkara,
                    lama_proses,
                    detail_url,
                    raw_json
                FROM perkara
                WHERE UPPER(termohon) LIKE ? OR UPPER(pemohon) LIKE ?
                ORDER BY tanggal_register DESC
            """, (q, q)).fetchall()
            conn.close()

            results = []
            for row in rows:
                record = {
                    "court": row["court"],
                    "nomor_perkara": row["nomor_perkara"],
                    "tanggal_register": row["tanggal_register"],
                    "klasifikasi": row["klasifikasi"],
                    "pemohon": row["pemohon"],
                    "termohon": row["termohon"],
                    "status_perkara": row["status_perkara"],
                    "lama_proses": row["lama_proses"],
                    "detail_url": row["detail_url"],
                }
                # Tambahkan detail dari raw_json jika tersedia
                if row["raw_json"]:
                    try:
                        raw = json.loads(row["raw_json"])
                        if "detail" in raw:
                            record["detail"] = raw["detail"]
                    except (json.JSONDecodeError, TypeError):
                        pass
                results.append(record)

            return results

        except Exception as e:
            print(f"   ⚠️ SIPP DB query error untuk '{entity_name}': {e}")
            return []

    @staticmethod
    def check_litigation_batch(entity_names: list) -> dict:
        """
        Memeriksa litigasi untuk banyak entitas sekaligus.

        Args:
            entity_names: List nama entitas

        Returns:
            Dict dengan key=nama entitas, value=list kasus (hanya yang ada hit)
        """
        results = {}
        for name in entity_names:
            if not name or not name.strip():
                continue
            cases = SIPPScraperTool.check_litigation(name)
            if cases:
                results[name] = cases
        return results

    # ──────────────────────────────────────────────────────────────────────────
    # Manual Override (load dari file JSON)
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def load_from_json(json_path: str) -> list:
        """
        Muat data litigasi dari file JSON (untuk manual upload / override).

        Format yang didukung:
        1. Array langsung: [ { "nomor_perkara": "...", ... }, ... ]
        2. Dengan wrapper: { "cases": [ {...}, ... ] }

        Args:
            json_path: Path ke file JSON berisi array data litigasi

        Returns:
            List of dict berisi detail kasus litigasi
        """
        try:
            path = Path(json_path)
            if not path.exists():
                print(f"   ⚠️ File tidak ditemukan: {json_path}")
                return []

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, list):
                print(f"   ✅ Data SIPP dimuat dari: {json_path} ({len(data)} kasus)")
                return data
            elif isinstance(data, dict) and "cases" in data:
                cases = data["cases"]
                print(f"   ✅ Data SIPP dimuat dari: {json_path} ({len(cases)} kasus)")
                return cases
            else:
                print(f"   ⚠️ Format JSON SIPP tidak dikenali. Menggunakan sebagai single entry.")
                return [data]

        except json.JSONDecodeError as e:
            print(f"   ⚠️ File JSON tidak valid: {str(e)}")
            return []

    @staticmethod
    def load_from_dict(data: list) -> list:
        """
        Validasi dan muat data litigasi dari list dict (input JSON langsung).

        Args:
            data: List of dict berisi data litigasi

        Returns:
            List of dict yang sudah divalidasi (hanya yang memiliki nomor_perkara)
        """
        validated = []
        for item in data:
            if isinstance(item, dict) and "nomor_perkara" in item:
                validated.append(item)
        return validated

    # ──────────────────────────────────────────────────────────────────────────
    # Stats / Info
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_db_stats() -> dict:
        """
        Kembalikan statistik data SIPP yang ada di DB.

        Returns:
            Dict berisi total_perkara, per_court breakdown
        """
        try:
            conn = init_db(SIPPScraperTool._db_path())
            total = conn.execute("SELECT COUNT(*) as n FROM perkara").fetchone()["n"]
            by_court = conn.execute(
                "SELECT court, COUNT(*) as n FROM perkara GROUP BY court ORDER BY n DESC"
            ).fetchall()
            conn.close()
            return {
                "total_perkara": total,
                "per_court": {r["court"]: r["n"] for r in by_court}
            }
        except Exception as e:
            return {"error": str(e)}