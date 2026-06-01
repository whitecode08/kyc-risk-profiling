"""
SIPP Scraper - Kepailitan & PKPU
5 Pengadilan Niaga: Surabaya, Jakarta Pusat, Medan, Makassar, Semarang

Juga mengelola tabel internal DB untuk AHU dan PPATK.

Usage:
    python scraper.py --court surabaya --output data/
    python scraper.py --court all --output data/
    python scraper.py --search "PT Maju Jaya" --court all
    python scraper.py --load-ahu examples/ANEKA_BINTANG_GADING.json
    python scraper.py --load-ppatk examples/ppatk_dttot_sample.json
    python scraper.py --load-ppatk examples/ppatk_dttot_sample.csv
"""

import csv
import io
import requests
from bs4 import BeautifulSoup
import json
import time
import sqlite3
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
import re
import sys
import os

# Allow running from any directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# ─── Config ───────────────────────────────────────────────────────────────────

COURTS = {
    "surabaya": {
        "name": "PN Niaga Surabaya",
        "base_url": "https://sipp.pn-surabayakota.go.id",
        "cf_protected": False,
        "kepailitan_path": "/list_perkara/type/N3BCYXJNVWFCZnNsZXlzY3BCQzNJVWM5eFF0UU1PekVWNzR1UEllLytYUGh1djlibjFtOEhCeStjOFBIVmZGSTc2QkFIR21HRHQ3ZHNBZWhVT1JVZkE9PQ==",
    },
    "jakarta": {
        "name": "PN Niaga Jakarta Pusat",
        "base_url": "https://sipp.pn-jakartapusat.go.id",
        "cf_protected": False,
        "kepailitan_path": None,  # struktur berbeda, perlu discovery
    },
    "medan": {
        "name": "PN Niaga Medan",
        "base_url": "https://sipp.pn-medankota.go.id",
        "cf_protected": True,  # Cloudflare
        "kepailitan_path": "/list_perkara/type/SFA0OUtIOUkyVUZVUHQvZ0pXWU1OTTN2YXJaTy9vZ3g4RzZkWitxRlhpWGNNdVI3dm0yZjlVdFhZL1FkTncwNy93QmpsZ1ZOeThiemcreURvSmxORVE9PQ==",
    },
    "makassar": {
        "name": "PN Niaga Makassar",
        "base_url": "https://sipp.pn-makassar.go.id",
        "cf_protected": False,
        "kepailitan_path": None,  # perlu discovery
    },
    "semarang": {
        "name": "PN Niaga Semarang",
        "base_url": "https://sipp.pn-semarangkota.go.id",
        "cf_protected": True,  # Cloudflare
        "kepailitan_path": None,
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "id-ID,id;q=0.9,en;q=0.8",
}

RATE_LIMIT_SECONDS = 4  # jeda antar request (3-7 detik sesuai etika)

# Default DB path (dapat di-override via env)
_DEFAULT_DB_PATH = os.environ.get("DB_PATH", "kyb_internal.db")

# ─── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("sipp_scraper.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ─── Database ─────────────────────────────────────────────────────────────────

def init_db(db_path: str = _DEFAULT_DB_PATH) -> sqlite3.Connection:
    """
    Inisialisasi seluruh tabel internal DB:
    - perkara   : data SIPP yang di-scrape
    - ahu       : profil perusahaan dari AHU (JSON/CSV)
    - ppatk     : daftar sanksi PPATK DTTOT (JSON/CSV)
    - scrape_log: log sesi crawling
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        -- ── SIPP Perkara ─────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS perkara (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            court           TEXT NOT NULL,
            nomor_perkara   TEXT UNIQUE NOT NULL,
            tanggal_register TEXT,
            klasifikasi     TEXT,
            pemohon         TEXT,
            termohon        TEXT,
            kuasa_pemohon   TEXT,
            kuasa_termohon  TEXT,
            status_perkara  TEXT,
            lama_proses     TEXT,
            detail_url      TEXT,
            raw_json        TEXT,
            scraped_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_termohon   ON perkara(termohon);
        CREATE INDEX IF NOT EXISTS idx_pemohon    ON perkara(pemohon);
        CREATE INDEX IF NOT EXISTS idx_court      ON perkara(court);
        CREATE INDEX IF NOT EXISTS idx_klasifikasi ON perkara(klasifikasi);

        -- ── AHU Company Profile ───────────────────────────────────────
        CREATE TABLE IF NOT EXISTS ahu (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            company_name TEXT NOT NULL,
            nib          TEXT,
            sk_number    TEXT,
            source_file  TEXT,
            json_data    TEXT NOT NULL,
            loaded_at    TEXT DEFAULT (datetime('now')),
            updated_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_ahu_name ON ahu(company_name);
        CREATE INDEX IF NOT EXISTS idx_ahu_nib         ON ahu(nib);

        -- ── PPATK DTTOT Sanctions ─────────────────────────────────────
        CREATE TABLE IF NOT EXISTS ppatk (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            id_dttot         TEXT UNIQUE NOT NULL,
            jenis            TEXT,
            nama             TEXT NOT NULL,
            nama_alias       TEXT,    -- JSON array as text
            tempat_lahir     TEXT,
            tanggal_lahir    TEXT,
            kewarganegaraan  TEXT,
            nomor_identitas  TEXT,
            jenis_identitas  TEXT,
            alamat           TEXT,
            kategori         TEXT,
            dasar_penetapan  TEXT,
            tanggal_penetapan TEXT,
            tanggal_berakhir TEXT,
            status           TEXT,
            keterangan       TEXT,
            daftar_asal      TEXT,
            source_file      TEXT,
            loaded_at        TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_ppatk_nama   ON ppatk(nama);
        CREATE INDEX IF NOT EXISTS idx_ppatk_status ON ppatk(status);

        -- ── Scrape Log ────────────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS scrape_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            court       TEXT,
            total_found INTEGER,
            scraped     INTEGER,
            errors      INTEGER,
            run_at      TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    return conn


# ─── AHU Loader ───────────────────────────────────────────────────────────────

def _extract_nib_from_ahu(data: dict) -> Optional[str]:
    """Coba ekstrak NIB dari field-field AHU JSON."""
    # NIB bisa ada di berbagai field
    for field in ["nib", "NIB", "companyNIB", "nibNumber"]:
        val = data.get(field) or data.get("company", {}).get(field)
        if val:
            return str(val)
    return None


def load_ahu_from_json(json_path: str, db_path: str = _DEFAULT_DB_PATH) -> dict:
    """
    Muat profil perusahaan dari file JSON AHU ke dalam tabel `ahu` di DB.

    Args:
        json_path: Path ke file JSON (format sesuai skema ANEKA BINTANG GADING.json)
        db_path:   Path ke SQLite database

    Returns:
        dict profil perusahaan yang di-load
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"File tidak ditemukan: {json_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "company" not in data:
        raise ValueError(f"Format JSON tidak valid: field 'company' tidak ditemukan di {json_path}")

    company_name = data["company"].get("name", "").strip().upper()
    if not company_name:
        raise ValueError(f"Nama perusahaan kosong di file: {json_path}")

    nib = _extract_nib_from_ahu(data)
    sk_number = data.get("company", {}).get("skNumber", "")

    conn = init_db(db_path)
    try:
        conn.execute("""
            INSERT INTO ahu (company_name, nib, sk_number, source_file, json_data, updated_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(company_name) DO UPDATE SET
                nib        = excluded.nib,
                sk_number  = excluded.sk_number,
                source_file = excluded.source_file,
                json_data  = excluded.json_data,
                updated_at = datetime('now')
        """, (company_name, nib, sk_number, str(path.resolve()), json.dumps(data, ensure_ascii=False)))
        conn.commit()
        log.info(f"[AHU] Loaded: {company_name} from {json_path}")
    finally:
        conn.close()

    return data


def load_ahu_from_csv(csv_path: str, db_path: str = _DEFAULT_DB_PATH) -> int:
    """
    Muat data AHU dari file CSV (flat export).

    CSV schema minimal (flat version dari JSON AHU):
    company_name, nib, sk_number, sk_date, company_type, status, address, province, json_data

    json_data kolom bisa berisi full JSON string, atau akan dibuat skeleton.

    Returns:
        Jumlah record yang berhasil di-load
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"File tidak ditemukan: {csv_path}")

    conn = init_db(db_path)
    count = 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                company_name = row.get("company_name", "").strip().upper()
                if not company_name:
                    continue

                # Jika ada kolom json_data, gunakan langsung
                if row.get("json_data"):
                    try:
                        data = json.loads(row["json_data"])
                    except json.JSONDecodeError:
                        data = _build_ahu_skeleton_from_csv_row(row)
                else:
                    # Bangun skeleton dari kolom CSV flat
                    data = _build_ahu_skeleton_from_csv_row(row)

                nib = row.get("nib", "").strip() or None
                sk_number = row.get("sk_number", "").strip()

                conn.execute("""
                    INSERT INTO ahu (company_name, nib, sk_number, source_file, json_data, updated_at)
                    VALUES (?, ?, ?, ?, ?, datetime('now'))
                    ON CONFLICT(company_name) DO UPDATE SET
                        nib        = excluded.nib,
                        sk_number  = excluded.sk_number,
                        source_file = excluded.source_file,
                        json_data  = excluded.json_data,
                        updated_at = datetime('now')
                """, (company_name, nib, sk_number, str(path.resolve()),
                      json.dumps(data, ensure_ascii=False)))
                count += 1

        conn.commit()
        log.info(f"[AHU] Loaded {count} companies from CSV: {csv_path}")
    finally:
        conn.close()

    return count


def _build_ahu_skeleton_from_csv_row(row: dict) -> dict:
    """Bangun dict AHU minimal dari baris CSV flat."""
    return {
        "isProfileComplete": False,
        "company": {
            "name": row.get("company_name", ""),
            "shortName": row.get("short_name", ""),
            "skNumber": row.get("sk_number", ""),
            "skDate": row.get("sk_date", ""),
            "spNumber": "",
            "spDate": "",
            "companySpNumber": "",
            "companySpDate": "",
            "type": row.get("company_type", ""),
            "timePeriod": row.get("time_period", "TIDAK TERBATAS"),
            "status": row.get("status", ""),
            "phoneNo": row.get("phone_no", ""),
            "transactionType": row.get("transaction_type", ""),
        },
        "companyAddress": {
            "address": row.get("address", ""),
            "rt": row.get("rt", "0"),
            "rw": row.get("rw", "0"),
            "postalCode": row.get("postal_code", ""),
            "ward": row.get("ward", ""),
            "subdistrict": row.get("subdistrict", ""),
            "regency": row.get("regency", ""),
            "province": row.get("province", ""),
        },
        "companyGoals": [],
        "notary": {},
        "baseStock": {},
        "issuedStock": {},
        "paidUpStock": row.get("paid_up_stock", ""),
        "shareholders": [],
    }


def search_ahu_db(query: str, db_path: str = _DEFAULT_DB_PATH) -> Optional[dict]:
    """
    Cari data AHU di DB berdasarkan nama perusahaan (case-insensitive partial match).

    Returns:
        dict profil perusahaan pertama yang cocok, atau None
    """
    conn = init_db(db_path)
    try:
        q = f"%{query.upper()}%"
        row = conn.execute(
            "SELECT json_data FROM ahu WHERE UPPER(company_name) LIKE ? ORDER BY updated_at DESC LIMIT 1",
            (q,)
        ).fetchone()
        if row:
            return json.loads(row["json_data"])
        return None
    finally:
        conn.close()


def search_ahu_by_nib(nib: str, db_path: str = _DEFAULT_DB_PATH) -> Optional[dict]:
    """Cari data AHU di DB berdasarkan NIB."""
    conn = init_db(db_path)
    try:
        row = conn.execute(
            "SELECT json_data FROM ahu WHERE nib = ? ORDER BY updated_at DESC LIMIT 1",
            (nib.strip(),)
        ).fetchone()
        if row:
            return json.loads(row["json_data"])
        return None
    finally:
        conn.close()


def get_all_ahu_companies(db_path: str = _DEFAULT_DB_PATH) -> dict:
    """Kembalikan semua perusahaan AHU di DB sebagai {company_name: nib}."""
    conn = init_db(db_path)
    try:
        rows = conn.execute("SELECT company_name, nib FROM ahu ORDER BY company_name").fetchall()
        return {r["company_name"]: r["nib"] or "-" for r in rows}
    finally:
        conn.close()


# ─── PPATK Loader ─────────────────────────────────────────────────────────────

def load_ppatk_from_json(json_path: str, db_path: str = _DEFAULT_DB_PATH) -> int:
    """
    Muat daftar PPATK DTTOT dari file JSON ke DB.

    Format JSON yang didukung:
    1. { "entries": [ {...}, ... ] }    ← format dengan wrapper metadata
    2. [ {...}, {...} ]                  ← array langsung

    Returns:
        Jumlah entri yang berhasil di-load
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"File tidak ditemukan: {json_path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # Support dua format: wrapper atau array langsung
    entries = raw.get("entries", raw) if isinstance(raw, dict) else raw
    if not isinstance(entries, list):
        raise ValueError(f"Format JSON PPATK tidak valid: harus berupa array atau {{entries: [...]}}")

    return _upsert_ppatk_entries(entries, str(path.resolve()), db_path)


def load_ppatk_from_csv(csv_path: str, db_path: str = _DEFAULT_DB_PATH) -> int:
    """
    Muat daftar PPATK DTTOT dari file CSV ke DB.

    Kolom CSV: id_dttot, jenis, nama, nama_alias (pipe-separated), tempat_lahir,
               tanggal_lahir, kewarganegaraan, nomor_identitas, jenis_identitas,
               alamat, kategori, dasar_penetapan, tanggal_penetapan, tanggal_berakhir,
               status, keterangan, daftar_asal

    Returns:
        Jumlah entri yang berhasil di-load
    """
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"File tidak ditemukan: {csv_path}")

    entries = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Konversi nama_alias dari pipe-separated ke list
            alias_raw = row.get("nama_alias", "")
            if alias_raw:
                aliases = [a.strip() for a in alias_raw.split("|") if a.strip()]
            else:
                aliases = []

            entry = {
                "id_dttot": row.get("id_dttot", "").strip(),
                "jenis": row.get("jenis", "").strip(),
                "nama": row.get("nama", "").strip(),
                "nama_alias": aliases,
                "tempat_lahir": row.get("tempat_lahir", "").strip() or None,
                "tanggal_lahir": row.get("tanggal_lahir", "").strip() or None,
                "kewarganegaraan": row.get("kewarganegaraan", "").strip() or None,
                "nomor_identitas": row.get("nomor_identitas", "").strip() or None,
                "jenis_identitas": row.get("jenis_identitas", "").strip() or None,
                "alamat": row.get("alamat", "").strip() or None,
                "kategori": row.get("kategori", "").strip(),
                "dasar_penetapan": row.get("dasar_penetapan", "").strip(),
                "tanggal_penetapan": row.get("tanggal_penetapan", "").strip() or None,
                "tanggal_berakhir": row.get("tanggal_berakhir", "").strip() or None,
                "status": row.get("status", "AKTIF").strip(),
                "keterangan": row.get("keterangan", "").strip(),
                "daftar_asal": row.get("daftar_asal", "").strip(),
            }
            if entry["id_dttot"] and entry["nama"]:
                entries.append(entry)

    return _upsert_ppatk_entries(entries, str(path.resolve()), db_path)


def _upsert_ppatk_entries(entries: list, source_file: str, db_path: str) -> int:
    """Helper: upsert list entri PPATK ke DB."""
    conn = init_db(db_path)
    count = 0
    try:
        for entry in entries:
            id_dttot = entry.get("id_dttot", "").strip()
            nama = entry.get("nama", "").strip().upper()
            if not id_dttot or not nama:
                continue

            alias_json = json.dumps(entry.get("nama_alias", []), ensure_ascii=False)
            conn.execute("""
                INSERT INTO ppatk (
                    id_dttot, jenis, nama, nama_alias, tempat_lahir, tanggal_lahir,
                    kewarganegaraan, nomor_identitas, jenis_identitas, alamat,
                    kategori, dasar_penetapan, tanggal_penetapan, tanggal_berakhir,
                    status, keterangan, daftar_asal, source_file
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id_dttot) DO UPDATE SET
                    nama            = excluded.nama,
                    nama_alias      = excluded.nama_alias,
                    status          = excluded.status,
                    keterangan      = excluded.keterangan,
                    tanggal_berakhir = excluded.tanggal_berakhir,
                    source_file     = excluded.source_file
            """, (
                id_dttot, entry.get("jenis"), nama,
                alias_json, entry.get("tempat_lahir"), entry.get("tanggal_lahir"),
                entry.get("kewarganegaraan"), entry.get("nomor_identitas"),
                entry.get("jenis_identitas"), entry.get("alamat"),
                entry.get("kategori"), entry.get("dasar_penetapan"),
                entry.get("tanggal_penetapan"), entry.get("tanggal_berakhir"),
                entry.get("status", "AKTIF"), entry.get("keterangan"),
                entry.get("daftar_asal"), source_file
            ))
            count += 1

        conn.commit()
        log.info(f"[PPATK] Loaded {count} entries from {source_file}")
    finally:
        conn.close()

    return count


def search_ppatk_db(entity_name: str, db_path: str = _DEFAULT_DB_PATH,
                    include_inactive: bool = False) -> list:
    """
    Cari entitas dalam daftar PPATK DTTOT menggunakan fuzzy match nama dan alias.

    Args:
        entity_name:      Nama yang dicari
        db_path:          Path SQLite DB
        include_inactive: Sertakan entri TIDAK AKTIF (default False)

    Returns:
        List of dict dengan detail entri PPATK yang cocok
    """
    conn = init_db(db_path)
    try:
        q = f"%{entity_name.upper()}%"
        status_filter = "" if include_inactive else "AND UPPER(status) = 'AKTIF'"
        rows = conn.execute(f"""
            SELECT id_dttot, jenis, nama, nama_alias, tempat_lahir, tanggal_lahir,
                   kewarganegaraan, nomor_identitas, kategori, dasar_penetapan,
                   tanggal_penetapan, tanggal_berakhir, status, keterangan, daftar_asal
            FROM ppatk
            WHERE (UPPER(nama) LIKE ? OR nama_alias LIKE ?)
            {status_filter}
            ORDER BY tanggal_penetapan DESC
        """, (q, q)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ─── Session Factory ──────────────────────────────────────────────────────────

def make_session(base_url: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.headers["Referer"] = base_url
    try:
        s.get(base_url, timeout=15)
        time.sleep(1)
    except Exception as e:
        log.warning(f"Homepage warmup failed: {e}")
    return s


# ─── List Page Parser ─────────────────────────────────────────────────────────

def parse_list_page(html: str, base_url: str) -> tuple[list[dict], Optional[str], int, int]:
    """
    Returns (records, next_page_url, current_page, total_pages).
    records = list of basic perkara info dari tabel daftar.
    """
    soup = BeautifulSoup(html, "lxml")
    records = []

    table = soup.find("table")
    if not table:
        return records, None, 1, 1

    rows = table.find_all("tr")[1:]  # skip header
    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 7:
            continue

        link_tag = row.find("a", href=True)
        detail_url = None
        if link_tag:
            href = link_tag["href"]
            # Pastikan absolute URL
            if href and href.startswith("http"):
                detail_url = href
            elif href and href.startswith("/"):
                detail_url = base_url.rstrip("/") + href

        # parse para pihak: pisahkan Pemohon dan Termohon
        para_pihak_raw = cells[4].get_text(separator=" ", strip=True)
        pemohon, termohon = split_para_pihak(para_pihak_raw)

        records.append({
            "nomor_perkara": cells[1].get_text(strip=True),
            "tanggal_register": cells[2].get_text(strip=True),
            "klasifikasi": cells[3].get_text(strip=True),
            "pemohon": pemohon,
            "termohon": termohon,
            "status_perkara": cells[5].get_text(strip=True),
            "lama_proses": cells[6].get_text(strip=True),
            "detail_url": detail_url,
        })

    # --- Pagination: SIPP pakai JS dengan pola /list_perkara/page/{n}/{token}/key ---
    next_url = None
    current_page = 1
    total_pages = 1

    # Extract dari JS: window.open('/list_perkara/page/'+pageNumber+'/TOKEN/key/...')
    js_match = re.search(
        r"window\.open\('(https?://[^']+/list_perkara/page/)'?\+pageNumber\+'(/[^']+)'",
        html
    )
    # Extract current page dan total dari JS vars
    page_match = re.search(r"var\s+page\s*=\s*['\"](\d+)['\"]", html)
    total_match = re.search(r"var\s+totalPage\s*=\s*['\"](\d+)['\"]", html)

    if page_match:
        current_page = int(page_match.group(1))
    if total_match:
        total_pages = int(total_match.group(1))

    if js_match and current_page < total_pages:
        base_part = js_match.group(1)   # e.g. https://sipp.../list_perkara/page/
        token_part = js_match.group(2)  # e.g. /TOKEN/key/col/2
        next_page = current_page + 1
        next_url = f"{base_part}{next_page}{token_part}"

    # Fallback: cari link Next di HTML biasa
    if not next_url:
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            if text in ["next", "›", "»", "selanjutnya"]:
                href = a["href"]
                if href and href != "#":
                    if href.startswith("http"):
                        next_url = href
                    else:
                        next_url = base_url.rstrip("/") + "/" + href.lstrip("/")
                break

    return records, next_url, current_page, total_pages


def split_para_pihak(raw: str) -> tuple[str, str]:
    """Extract Pemohon dan Termohon dari string para pihak."""
    pemohon = ""
    termohon = ""

    p_match = re.search(r"Pemohon\s*:\s*(.*?)(?=Termohon\s*:|$)", raw, re.IGNORECASE | re.DOTALL)
    t_match = re.search(r"Termohon\s*:\s*(.*?)$", raw, re.IGNORECASE | re.DOTALL)

    if p_match:
        pemohon = re.sub(r"\s+", " ", p_match.group(1)).strip()
    if t_match:
        termohon = re.sub(r"\s+", " ", t_match.group(1)).strip()

    if not pemohon and not termohon:
        # fallback: return raw
        pemohon = raw.strip()

    return pemohon, termohon


# ─── Detail Page Parser ───────────────────────────────────────────────────────

def parse_detail_page(html: str) -> dict:
    """Ekstrak detail lengkap dari halaman detail perkara."""
    soup = BeautifulSoup(html, "lxml")
    detail = {}

    tables = soup.find_all("table")
    if not tables:
        return detail

    # Iterasi semua tabel, kumpulkan key-value pair
    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) == 2:
                key = cells[0].get_text(strip=True)
                val = cells[1].get_text(separator=" ", strip=True)
                if key and not key.isdigit() and len(key) < 80:
                    detail[key] = val

    # Ekstrak nama-nama pihak dari sub-tabel No/Nama
    party_fields = {}
    for table in tables:
        header_row = table.find("tr")
        if not header_row:
            continue
        headers = [th.get_text(strip=True).lower() for th in header_row.find_all(["th", "td"])]
        if "nama" in headers or "no" in headers:
            names = extract_names_from_subtable(table)
            if names:
                # Tentukan konteks dari elemen sebelum tabel
                prev = table.find_previous(["h4", "h3", "p", "strong"])
                context_key = prev.get_text(strip=True) if prev else "pihak"
                party_fields[context_key] = names

    if party_fields:
        detail["pihak_detail"] = party_fields

    return detail


def extract_names_from_subtable(table) -> list[str]:
    """Extract nama-nama dari sub-tabel No/Nama."""
    names = []
    rows = table.find_all("tr")
    for row in rows[1:]:  # skip header
        cells = row.find_all("td")
        if len(cells) >= 2:
            try:
                int(cells[0].get_text(strip=True))
                name = cells[1].get_text(strip=True)
                if name:
                    names.append(name)
            except ValueError:
                pass
    return names


# ─── Core Crawler ─────────────────────────────────────────────────────────────

class SIPPCrawler:
    def __init__(self, court_key: str, db: sqlite3.Connection, output_dir: Path):
        self.court_key = court_key
        self.court = COURTS[court_key]
        self.db = db
        self.output_dir = output_dir
        self.session = make_session(self.court["base_url"])
        self.stats = {"found": 0, "scraped": 0, "skipped": 0, "errors": 0}

    def _get(self, url: str) -> Optional[requests.Response]:
        try:
            r = self.session.get(url, timeout=20)
            r.raise_for_status()
            return r
        except requests.exceptions.HTTPError as e:
            log.error(f"HTTP {e.response.status_code} for {url}")
        except requests.exceptions.Timeout:
            log.error(f"Timeout for {url}")
        except Exception as e:
            log.error(f"Request error for {url}: {e}")
        return None

    def discover_kepailitan_url(self) -> Optional[str]:
        """Auto-discover URL daftar kepailitan dari homepage."""
        if self.court.get("kepailitan_path"):
            return self.court["base_url"] + self.court["kepailitan_path"]

        r = self._get(self.court["base_url"])
        if not r:
            return None

        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True).lower()
            href = a["href"]
            if "kepailitan" in text or "pkpu" in text:
                if href.startswith("http"):
                    return href
                return self.court["base_url"].rstrip("/") + "/" + href.lstrip("/")

        log.warning(f"Could not discover kepailitan URL for {self.court['name']}")
        return None

    def crawl_list(self, start_url: str) -> list[dict]:
        """Crawl semua halaman daftar perkara, return list semua record."""
        all_records = []
        url = start_url
        page = 1

        while url:
            log.info(f"[{self.court['name']}] List page {page}: {url}")
            r = self._get(url)
            if not r:
                break

            records, next_url, current_page, total_pages = parse_list_page(r.text, self.court["base_url"])
            all_records.extend(records)
            log.info(f"  -> {len(records)} records | page {current_page}/{total_pages} | total so far: {len(all_records)}")

            if not next_url or next_url == url:
                break

            url = next_url
            page += 1
            time.sleep(RATE_LIMIT_SECONDS)

        self.stats["found"] = len(all_records)
        return all_records

    def crawl_detail(self, record: dict) -> dict:
        """Fetch dan parse halaman detail perkara."""
        if not record.get("detail_url"):
            return record

        r = self._get(record["detail_url"])
        if not r:
            self.stats["errors"] += 1
            return record

        detail = parse_detail_page(r.text)
        record["detail"] = detail
        return record

    def save_record(self, record: dict):
        """Simpan ke SQLite, upsert berdasarkan nomor_perkara."""
        try:
            self.db.execute("""
                INSERT INTO perkara 
                    (court, nomor_perkara, tanggal_register, klasifikasi,
                     pemohon, termohon, status_perkara, lama_proses, detail_url, raw_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(nomor_perkara) DO UPDATE SET
                    status_perkara = excluded.status_perkara,
                    lama_proses    = excluded.lama_proses,
                    raw_json       = excluded.raw_json,
                    updated_at     = datetime('now')
            """, (
                self.court_key,
                record.get("nomor_perkara"),
                record.get("tanggal_register"),
                record.get("klasifikasi"),
                record.get("pemohon"),
                record.get("termohon"),
                record.get("status_perkara"),
                record.get("lama_proses"),
                record.get("detail_url"),
                json.dumps(record, ensure_ascii=False),
            ))
            self.db.commit()
            self.stats["scraped"] += 1
        except Exception as e:
            log.error(f"DB error for {record.get('nomor_perkara')}: {e}")
            self.stats["errors"] += 1

    def run(self, fetch_detail: bool = False):
        """Main crawl loop."""
        if self.court.get("cf_protected"):
            log.warning(f"[{self.court['name']}] Protected by Cloudflare — skipping (perlu residential proxy atau Playwright stealth)")
            return

        start_url = self.discover_kepailitan_url()
        if not start_url:
            log.error(f"[{self.court['name']}] Cannot find kepailitan URL")
            return

        log.info(f"[{self.court['name']}] Starting crawl from: {start_url}")
        records = self.crawl_list(start_url)

        for i, record in enumerate(records):
            # cek apakah sudah ada di DB
            existing = self.db.execute(
                "SELECT id FROM perkara WHERE nomor_perkara = ?",
                (record.get("nomor_perkara"),)
            ).fetchone()

            if existing and not fetch_detail:
                self.stats["skipped"] += 1
                continue

            if fetch_detail:
                log.info(f"  Detail {i+1}/{len(records)}: {record.get('nomor_perkara')}")
                record = self.crawl_detail(record)
                time.sleep(RATE_LIMIT_SECONDS)

            self.save_record(record)

        # log run stats
        self.db.execute("""
            INSERT INTO scrape_log (court, total_found, scraped, errors)
            VALUES (?, ?, ?, ?)
        """, (self.court_key, self.stats["found"], self.stats["scraped"], self.stats["errors"]))
        self.db.commit()

        log.info(f"[{self.court['name']}] Done: {self.stats}")


# ─── Search ───────────────────────────────────────────────────────────────────

def search_db(db: sqlite3.Connection, query: str) -> list[dict]:
    """Search perkara by nama perusahaan (fuzzy match di pemohon/termohon)."""
    q = f"%{query}%"
    rows = db.execute("""
        SELECT court, nomor_perkara, tanggal_register, klasifikasi,
               pemohon, termohon, status_perkara
        FROM perkara
        WHERE termohon LIKE ? OR pemohon LIKE ?
        ORDER BY tanggal_register DESC
    """, (q, q)).fetchall()
    return [dict(r) for r in rows]


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="KYB Internal DB Manager & SIPP Kepailitan/PKPU Scraper")
    parser.add_argument("--court", default="surabaya",
                        choices=list(COURTS.keys()) + ["all"],
                        help="Pengadilan yang di-crawl")
    parser.add_argument("--output", default="data", help="Output directory")
    parser.add_argument("--db", default=_DEFAULT_DB_PATH, help="SQLite database path")
    parser.add_argument("--detail", action="store_true",
                        help="Fetch halaman detail setiap perkara")
    parser.add_argument("--search", help="Search nama perusahaan di DB yang sudah ada")
    parser.add_argument("--export", help="Export hasil ke JSON file")
    parser.add_argument("--load-ahu", dest="load_ahu", metavar="FILE",
                        help="Load AHU data dari file JSON/CSV ke DB")
    parser.add_argument("--load-ppatk", dest="load_ppatk", metavar="FILE",
                        help="Load PPATK DTTOT dari file JSON/CSV ke DB")
    parser.add_argument("--init-only", action="store_true",
                        help="Hanya inisialisasi DB (buat tabel) tanpa crawling")
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Mode: init DB only
    if args.init_only:
        conn = init_db(args.db)
        conn.close()
        log.info(f"DB diinisialisasi: {args.db}")
        return

    # Mode: Load AHU data
    if args.load_ahu:
        file_path = args.load_ahu
        ext = Path(file_path).suffix.lower()
        if ext == ".json":
            data = load_ahu_from_json(file_path, args.db)
            print(f"✅ AHU JSON dimuat: {data.get('company', {}).get('name', 'Unknown')}")
        elif ext == ".csv":
            count = load_ahu_from_csv(file_path, args.db)
            print(f"✅ AHU CSV dimuat: {count} perusahaan")
        else:
            print(f"❌ Format tidak didukung: {ext}. Gunakan .json atau .csv")
        return

    # Mode: Load PPATK data
    if args.load_ppatk:
        file_path = args.load_ppatk
        ext = Path(file_path).suffix.lower()
        if ext == ".json":
            count = load_ppatk_from_json(file_path, args.db)
        elif ext == ".csv":
            count = load_ppatk_from_csv(file_path, args.db)
        else:
            print(f"❌ Format tidak didukung: {ext}. Gunakan .json atau .csv")
            return
        print(f"✅ PPATK DTTOT dimuat: {count} entri")
        return

    db = init_db(args.db)

    # Mode search
    if args.search:
        results = search_db(db, args.search)
        print(f"\n=== Hasil pencarian SIPP: '{args.search}' ({len(results)} perkara) ===\n")
        for r in results:
            print(f"[{r['court'].upper()}] {r['nomor_perkara']}")
            print(f"  Klasifikasi : {r['klasifikasi']}")
            print(f"  Pemohon     : {r['pemohon'][:80]}")
            print(f"  Termohon    : {r['termohon'][:80]}")
            print(f"  Status      : {r['status_perkara']}")
            print(f"  Register    : {r['tanggal_register']}")
            print()

        if args.export:
            with open(args.export, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"Exported to {args.export}")
        return

    # Mode crawl
    courts_to_crawl = list(COURTS.keys()) if args.court == "all" else [args.court]

    for court_key in courts_to_crawl:
        crawler = SIPPCrawler(court_key, db, output_dir)
        crawler.run(fetch_detail=args.detail)

    # Summary
    total = db.execute("SELECT COUNT(*) FROM perkara").fetchone()[0]
    log.info(f"\n=== Total perkara di DB: {total} ===")


if __name__ == "__main__":
    main()
