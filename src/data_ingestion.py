"""
KYB Intelligence Pipeline — Data Ingestion
============================================
- Load AHU JSON dari data/input/ahu/
- Load PPATK JSON dari data/input/ppatk/
- Extract Top 5 UBO (pemegang saham terbesar)
"""

import json
import re
import glob
from pathlib import Path
from src.config import INPUT_DIR


# ─── Naming Utilities ─────────────────────────────────────────────────────────

def extract_db_number(filepath: str) -> str:
    """
    Extract database number prefix from input filename.

    Examples:
        '01__ahu__aneka_bintang_gading.json' → '01'
        'aneka_bintang_gading.json' → '00'
    """
    name = Path(filepath).stem
    match = re.match(r'^(\d+)__', name)
    return match.group(1) if match else "00"


def make_output_filename(db_number: str, category: str, company_name: str, ext: str = ".json") -> str:
    """
    Generate standardized output filename.

    Format: {db_number}__{category}__{lower(company_name)}{ext}
    Example: 01__osint__aneka_bintang_gading.json
    """
    safe = company_name.lower().replace(" ", "_").replace("/", "-")
    return f"{db_number}__{category}__{safe}{ext}"


# ─── AHU Loader ───────────────────────────────────────────────────────────────

def load_ahu_json(json_path: str) -> tuple:
    """
    Muat profil perusahaan dari file JSON AHU.

    Args:
        json_path: Path ke file JSON (format skema Ditjen AHU)

    Returns:
        tuple (dict profil perusahaan, str db_number)
    """
    path = Path(json_path)
    if not path.exists():
        raise FileNotFoundError(f"File AHU tidak ditemukan: {json_path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "company" not in data:
        raise ValueError(f"Format JSON tidak valid: field 'company' tidak ditemukan di {json_path}")

    company_name = data.get("company", {}).get("name", "").strip()
    if not company_name:
        raise ValueError(f"Nama perusahaan kosong di file: {json_path}")

    db_number = extract_db_number(str(path))

    print(f"   ✅ AHU: Dimuat dari {path.name} — {company_name} (DB #{db_number})")
    return data, db_number


def scan_ahu_folder() -> dict:
    """
    Scan semua file JSON di data/input/ahu/ dan return mapping {company_name: path}.
    """
    ahu_dir = INPUT_DIR / "ahu"
    if not ahu_dir.exists():
        return {}

    companies = {}
    for f in sorted(ahu_dir.glob("*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            name = data.get("company", {}).get("name", "")
            if name:
                companies[name.upper()] = str(f)
        except Exception:
            pass

    return companies


def find_ahu_by_name(company_name: str) -> tuple:
    """
    Cari file AHU di data/input/ahu/ berdasarkan nama perusahaan (partial match).

    Returns:
        tuple (dict profil perusahaan, str db_number), atau (dict dengan key 'error', '00')
    """
    companies = scan_ahu_folder()
    query = company_name.upper()

    # Exact match first
    for name, path in companies.items():
        if name == query:
            return load_ahu_json(path)

    # Partial match
    for name, path in companies.items():
        if query in name or name in query:
            return load_ahu_json(path)

    return {"error": f"Data AHU tidak ditemukan untuk: '{company_name}'. "
                     f"Perusahaan tersedia: {', '.join(companies.keys()) or 'kosong'}"}, "00"




# ─── UBO Extraction ──────────────────────────────────────────────────────────

def _is_corporate_name(name: str) -> bool:
    """
    Deteksi apakah nama adalah badan hukum (PT/CV) menggunakan word-boundary.

    Rules (case-insensitive):
      - Diawali dengan "PT " atau "CV "  → korporasi
      - Diakhiri dengan " PT" atau " CV" → korporasi
      Substring match sengaja DIHINDARI untuk mencegah false positive
      seperti "CIPTA" (mengandung "PT") atau "ACVB" (mengandung "CV").
    """
    n = name.strip().upper()
    prefixes = ("PT ", "CV ")
    suffixes = (" PT", " CV")
    return n.startswith(prefixes) or n.endswith(suffixes)


def extract_all_ubo(ahu_data: dict) -> list:
    """
    Ekstrak Seluruh Pemegang Saham (UBO) berdasarkan numberOfShares.

    Framework: "Fungsi ini harus memilah array shareholders, mengurutkannya
    berdasarkan numberOfShares atau persentase, dan mengembalikan data Seluruh
    Pemegang Saham (UBO) untuk diteruskan ke proses OSINT dan dilaporkan."

    Args:
        ahu_data: dict profil AHU lengkap

    Returns:
        List of dict, masing-masing berisi nama, position, shares, percentage
    """
    shareholders = ahu_data.get("shareholders", [])
    paid_up_str = ahu_data.get("paidUpStock", "0")

    # Parse total saham
    try:
        total_shares = int(
            paid_up_str.replace("Rp. ", "").replace(",", "").replace(".", "").strip()
        )
    except (ValueError, AttributeError):
        total_shares = 500_000_000

    # Parse numberOfShares dan sort descending
    parsed = []
    for sh in shareholders:
        try:
            n_shares = int(sh.get("numberOfShares", "0"))
        except (ValueError, TypeError):
            n_shares = 0

        pct = (n_shares / total_shares * 100) if total_shares > 0 else 0

        parsed.append({
            "name": sh.get("name", ""),
            "position": sh.get("position", "-"),
            "numberOfShares": n_shares,
            "percentage": round(pct, 2),
            "address": sh.get("address", ""),
            "country": sh.get("country", "Indonesia"),
            "is_corporate": _is_corporate_name(sh.get("name", "")),
        })

    # Sort by shares descending, do not limit
    parsed.sort(key=lambda x: x["numberOfShares"], reverse=True)
    all_ubo = parsed

    if all_ubo:
        print(f"   📊 All UBO / Shareholders:")
        for i, ubo in enumerate(all_ubo, 1):
            flag = "🏢" if ubo["is_corporate"] else "👤"
            print(f"      {i}. {flag} {ubo['name']} — {ubo['percentage']}% ({ubo['position']})")

    return all_ubo


def get_company_metadata(ahu_data: dict) -> dict:
    """Ekstrak metadata perusahaan dari AHU data."""
    company = ahu_data.get("company", {})
    return {
        "name": company.get("name", ""),
        "sk_number": company.get("skNumber", ""),
        "company_type": company.get("type", ""),
        "status": company.get("status", ""),
        "transaction_type": company.get("transactionType", ""),
    }


# ─── PPATK Loader ─────────────────────────────────────────────────────────────

def load_all_ppatk() -> list:
    """
    Scan dan muat semua file PPATK dari data/input/ppatk/.

    Returns:
        List of dict — semua entri PPATK digabung
    """
    ppatk_dir = INPUT_DIR / "ppatk"
    if not ppatk_dir.exists():
        return []

    all_entries = []
    for f in sorted(ppatk_dir.glob("*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                raw = json.load(fh)

            # Support dua format: wrapper atau array langsung
            if isinstance(raw, dict):
                entries = raw.get("entries", [])
            elif isinstance(raw, list):
                entries = raw
            else:
                continue

            all_entries.extend(entries)
            print(f"   ✅ PPATK: Dimuat {len(entries)} entri dari {f.name}")
        except Exception as e:
            print(f"   ⚠️ PPATK: Gagal muat {f.name}: {e}")

    return all_entries


def screen_ppatk(entity_names: list, ppatk_entries: list) -> dict:
    """
    Screening nama entitas terhadap daftar PPATK DTTOT (in-memory, tanpa SQLite).

    Args:
        entity_names: List nama entitas yang akan diperiksa
        ppatk_entries: List entri PPATK yang sudah dimuat

    Returns:
        Dict ringkasan screening
    """
    hits = {}
    hit_categories = set()
    hit_sources = set()
    has_active = False

    for entity in entity_names:
        if not entity or not entity.strip():
            continue

        entity_upper = entity.strip().upper()
        entity_hits = []

        for entry in ppatk_entries:
            nama = entry.get("nama", "").upper()
            aliases = entry.get("nama_alias", [])
            if isinstance(aliases, str):
                aliases = [aliases]
            alias_upper = [a.upper() for a in aliases if a]

            # Fuzzy match: entity name contains or is contained in PPATK name
            matched = (
                entity_upper in nama
                or nama in entity_upper
                or any(entity_upper in a or a in entity_upper for a in alias_upper)
            )

            if matched:
                entity_hits.append(entry)
                if entry.get("kategori"):
                    hit_categories.add(entry["kategori"])
                if entry.get("daftar_asal"):
                    hit_sources.add(entry["daftar_asal"])
                if entry.get("status", "").upper() == "AKTIF":
                    has_active = True

        if entity_hits:
            hits[entity] = entity_hits

    return {
        "total_checked": len([n for n in entity_names if n and n.strip()]),
        "total_hits": len(hits),
        "has_active_sanctions": has_active,
        "hits": hits,
        "hit_categories": sorted(hit_categories),
        "hit_sources": sorted(hit_sources),
    }
