"""
PPATK Tool - Screening Daftar Terduga Teroris dan Organisasi Teroris (DTTOT)

Mengelola data PPATK yang bersumber dari:
- File JSON (format: examples/ppatk_dttot_sample.json)
- File CSV  (format: examples/ppatk_dttot_sample.csv)

Data disimpan di internal DB (SQLite) untuk lookup cepat selama profiling.

Regulasi terkait:
- Peraturan PPATK No. 2 Tahun 2023 tentang Targeted Financial Sanctions
- UU No. 8 Tahun 2010 tentang Pencegahan dan Pemberantasan TPPU
- Perpres No. 18 Tahun 2017 tentang Tata Cara Penerimaan dan Pemberian Informasi PPATK
"""

import json
from src.core.config import Config
from src.tools.scraper import (
    init_db, load_ppatk_from_json, load_ppatk_from_csv, search_ppatk_db
)


class PPATKTool:
    """
    Tool untuk memeriksa entitas terhadap daftar sanksi PPATK DTTOT.

    Flow:
    1. Data PPATK diimport dari file JSON/CSV ke internal DB via load_from_json() / load_from_csv()
    2. Saat profiling, check_entity() / check_batch() melakukan query ke DB
    3. Hasil dikembalikan sebagai list dict yang siap dipakai oleh researcher_agent
    """

    @staticmethod
    def _db_path() -> str:
        return Config.DB_PATH

    # ──────────────────────────────────────────────────────────────────────────
    # Data Loading (import ke DB)
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def load_from_json(json_path: str) -> int:
        """
        Muat daftar PPATK DTTOT dari file JSON ke internal DB.

        Format yang didukung:
        1. { "metadata": {...}, "entries": [ {...}, ... ] }  ← format dengan wrapper
        2. [ {...}, {...} ]                                    ← array langsung

        Setiap entry HARUS memiliki field: id_dttot, nama
        Field opsional: jenis, nama_alias, tempat_lahir, tanggal_lahir,
                        kewarganegaraan, nomor_identitas, kategori, status, dst.

        Args:
            json_path: Path ke file JSON PPATK

        Returns:
            Jumlah entri yang berhasil diimport
        """
        try:
            count = load_ppatk_from_json(json_path, db_path=PPATKTool._db_path())
            print(f"   ✅ PPATK JSON dimuat dari: {json_path} ({count} entri)")
            return count
        except FileNotFoundError:
            print(f"   ❌ File tidak ditemukan: {json_path}")
            return 0
        except ValueError as e:
            print(f"   ❌ Format JSON tidak valid: {e}")
            return 0
        except Exception as e:
            print(f"   ❌ Gagal memuat PPATK JSON: {e}")
            return 0

    @staticmethod
    def load_from_csv(csv_path: str) -> int:
        """
        Muat daftar PPATK DTTOT dari file CSV ke internal DB.

        Kolom CSV (header baris pertama):
            id_dttot, jenis, nama, nama_alias (pipe-separated), tempat_lahir,
            tanggal_lahir, kewarganegaraan, nomor_identitas, jenis_identitas,
            alamat, kategori, dasar_penetapan, tanggal_penetapan,
            tanggal_berakhir, status, keterangan, daftar_asal

        Args:
            csv_path: Path ke file CSV PPATK

        Returns:
            Jumlah entri yang berhasil diimport
        """
        try:
            count = load_ppatk_from_csv(csv_path, db_path=PPATKTool._db_path())
            print(f"   ✅ PPATK CSV dimuat dari: {csv_path} ({count} entri)")
            return count
        except FileNotFoundError:
            print(f"   ❌ File tidak ditemukan: {csv_path}")
            return 0
        except Exception as e:
            print(f"   ❌ Gagal memuat PPATK CSV: {e}")
            return 0

    # ──────────────────────────────────────────────────────────────────────────
    # Screening Methods (query DB)
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def check_entity(entity_name: str, include_inactive: bool = False) -> list:
        """
        Periksa apakah nama entitas ada dalam daftar PPATK DTTOT.

        Pencarian dilakukan terhadap:
        - Kolom `nama` (fuzzy/partial match)
        - Kolom `nama_alias` (JSON array stored as text)

        Args:
            entity_name:      Nama perusahaan atau individu yang diperiksa
            include_inactive: Sertakan entri dengan status 'TIDAK AKTIF' (default False)

        Returns:
            List of dict berisi detail entri yang cocok. List kosong = tidak ada hit.
            Contoh output:
            [{
                "id_dttot": "DTTOT-IND-2024-001",
                "jenis": "Individu",
                "nama": "AHMAD ZAINI MUTTAQIN",
                "kategori": "DTTOT",
                "status": "AKTIF",
                "dasar_penetapan": "Keputusan BNPT No. 123/2024",
                "tanggal_penetapan": "2024-03-01",
                "keterangan": "...",
                "daftar_asal": "Domestik - BNPT"
            }]
        """
        if not entity_name or not entity_name.strip():
            return []

        results = search_ppatk_db(
            entity_name.strip(),
            db_path=PPATKTool._db_path(),
            include_inactive=include_inactive
        )
        return results

    @staticmethod
    def check_batch(entity_names: list, include_inactive: bool = False) -> dict:
        """
        Periksa daftar nama entitas sekaligus terhadap PPATK DTTOT.

        Args:
            entity_names:     List nama entitas (perusahaan + semua pemegang saham/pengurus)
            include_inactive: Sertakan entri TIDAK AKTIF

        Returns:
            Dict {entity_name: [list_of_hits]}. Hanya entitas dengan hit yang masuk.
        """
        results = {}
        for name in entity_names:
            if not name or not name.strip():
                continue
            hits = PPATKTool.check_entity(name, include_inactive=include_inactive)
            if hits:
                results[name] = hits
        return results

    @staticmethod
    def get_screening_summary(entity_names: list) -> dict:
        """
        Hasilkan ringkasan screening PPATK untuk semua entitas.

        Args:
            entity_names: List semua nama entitas yang akan diperiksa

        Returns:
            Dict ringkasan untuk digunakan dalam context AI agent:
            {
                "total_checked": N,
                "total_hits": N,
                "has_active_sanctions": bool,
                "hits": { entity_name: [hit_detail] },
                "hit_categories": ["DTTOT", "TPPU", ...],
                "hit_sources": ["Domestik - BNPT", "Internasional - OFAC SDN", ...]
            }
        """
        batch_results = PPATKTool.check_batch(entity_names)

        hit_categories = set()
        hit_sources = set()
        has_active = False

        for entity, hits in batch_results.items():
            for hit in hits:
                if hit.get("kategori"):
                    hit_categories.add(hit["kategori"])
                if hit.get("daftar_asal"):
                    hit_sources.add(hit["daftar_asal"])
                if hit.get("status", "").upper() == "AKTIF":
                    has_active = True

        return {
            "total_checked": len([n for n in entity_names if n and n.strip()]),
            "total_hits": len(batch_results),
            "has_active_sanctions": has_active,
            "hits": batch_results,
            "hit_categories": sorted(hit_categories),
            "hit_sources": sorted(hit_sources),
        }
