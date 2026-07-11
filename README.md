# AI-KYB Customer Profiling System

**Autonomous Intelligence Pipeline untuk Know Your Business (KYB) & Anti-Money Laundering (AML)**

Sistem profiling perusahaan berbasis multi-agent AI yang mengotomasi pengumpulan, analisis, dan penilaian risiko nasabah korporat — sesuai regulasi OJK, PPATK, dan standar FATF.

---

## Fitur Utama

- **Multi-Agent Pipeline** — Researcher → Internet Research → Drafter → Critic (self-correction loop)
- **Data AHU** — Baca profil perusahaan dari file JSON/CSV Ditjen AHU, simpan ke internal DB
- **Data PPATK DTTOT** — Screening sanksi keuangan terarah dari file JSON/CSV, query otomatis per-run
- **SIPP Litigasi** — Scraping real-time dari 5 Pengadilan Niaga (Kepailitan & PKPU)
- **Internet OSINT** — Google Search Grounding: adverse media, sanctions, PEP detection
- **UBO Analysis** — Kalkulasi persentase kepemilikan, deteksi UBO ≥25% (per PPATK)
- **Risk Scoring (1–100)** — Otomatis, konsisten, dan tervalidasi oleh Critic Agent
- **Output JSON + PDF** — Profil lengkap + laporan siap cetak per perusahaan

---

## Arsitektur Pipeline

```
┌─────────────────── DATA SOURCES ───────────────────────┐
│  AHU JSON/CSV    PPATK JSON/CSV     SIPP Web (scraped) │
│       └──────────────┴───────────────────┘             │
│                        ▼                               │
│               kyb_internal.db (SQLite)                 │
│          ahu table │ ppatk table │ perkara table        │
└────────────────────────┼───────────────────────────────┘
                         ▼
     ┌─────────────────────────────────────────┐
     │  FASE 1: Researcher Agent               │
     │  · AHU lookup (nama / NIB)              │
     │  · SIPP litigasi (perusahaan + pengurus)│
     │  · PPATK DTTOT screening                │
     └────────────────┬────────────────────────┘
                      ▼
     ┌─────────────────────────────────────────┐
     │  FASE 2: Internet Research Agent        │
     │  · Adverse media (Google Search)        │
     │  · Sanctions (OFAC, UN, EU, PPATK)      │
     │  · PEP detection                        │
     └────────────────┬────────────────────────┘
                      ▼
     ┌─────────────────────────────────────────┐
     │  FASE 3: Drafter ↔ Critic Loop          │
     │  · Structured risk assessment           │
     │  · UBO analysis & scoring (1-100)       │
     │  · Self-correction (max 3 revisions)    │
     └────────────────┬────────────────────────┘
                      ▼
     ┌─────────────────────────────────────────┐
     │  FASE 4: Output Generation              │
     │  · JSON database (output/)              │
     │  · PDF report                           │
     │  · HCAT shadow evaluation               │
     └─────────────────────────────────────────┘
```

---

## Prasyarat

- Python 3.10+
- Gemini API Key ([Google AI Studio](https://aistudio.google.com))

---

## Instalasi

```bash
# 1. Clone atau ekstrak project
cd customer-profiling-ai

# 2. Buat virtual environment
python -m venv .venv

# 3. Aktifkan venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Konfigurasi API key — edit file .env
```

### Konfigurasi `.env`

```env
GEMINI_API_KEY="your-gemini-api-key-here"
HEAVY_IO_MODEL="gemini-2.5-flash"
COMPLEX_REASONING_MODEL="gemini-2.5-flash"
EMBEDDING_MODEL="gemini-embedding-001"
DB_PATH="kyb_internal.db"
```

---

## Cara Penggunaan

### Step 1 — Import Data ke Internal DB

```bash
# Import profil perusahaan dari AHU (JSON format)
python src/tools/scraper.py --load-ahu "path/to/ahu_data.json"

# Import daftar sanksi PPATK DTTOT (JSON atau CSV)
python src/tools/scraper.py --load-ppatk path/to/ppatk_data.json
python src/tools/scraper.py --load-ppatk path/to/ppatk_data.csv

# (Opsional) Scrape data litigasi SIPP dari web
python src/tools/scraper.py --court surabaya
python src/tools/scraper.py --court all
```

### Step 2 — Jalankan Pipeline

```bash
# Jalankan secara interaktif (default)
python run_pipeline.py

# Atau gunakan mode CLI langsung:
python run_pipeline.py --json data/input/ahu/01__ahu__aneka_bintang_gading.json
python run_pipeline.py --company "ANEKA BINTANG GADING" --nib 1234567890
```

**Mode 1 — Cari berdasarkan nama (dari folder data/input/ahu/):**
```
📋 PILIH MODE INPUT DATA:
────────────────────────────────────────────
  [1] Cari nama perusahaan di folder data/input/ahu/
  [2] Input path file JSON AHU
────────────────────────────────────────────

🔹 Pilih mode (1/2): 1

   📋 Perusahaan tersedia:
      1. 01__ahu__aneka_bintang_gading
      2. 02__ahu__mitra_sentosa

   Nama perusahaan: ANEKA BINTANG GADING
```

**Mode 2 — Input Path File JSON AHU:**
```
🔹 Pilih mode (1/2): 2

   Path file JSON AHU: data/input/ahu/01__ahu__aneka_bintang_gading.json
```

---

## Format Data

### AHU JSON

Contoh struktur skema data AHU:

```json
{
  "company": {
    "name": "NAMA PERUSAHAAN",
    "skNumber": "AHU-XXXXXXX.AH.01.02.Tahun XXXX",
    "type": "PMDN NON FASILITAS",
    "status": "TERTUTUP"
  },
  "companyAddress": { "province": "DKI JAKARTA", "regency": "JAKARTA UTARA" },
  "companyGoals": [{ "no": 1, "code": "56101", "name": "RESTORAN" }],
  "notary": { "name": "Nama Notaris", "deedNumber": "16" },
  "baseStock": { "numberOfShares": "500000000", "grandTotal": "Rp. 500,000,000" },
  "paidUpStock": "Rp. 500,000,000",
  "shareholders": [
    {
      "name": "NAMA PEMEGANG SAHAM",
      "position": "DIREKTUR UTAMA",
      "numberOfShares": "102600000"
    }
  ]
}
```

### PPATK DTTOT JSON

```json
{
  "entries": [
    {
      "id_dttot": "DTTOT-IND-2024-001",
      "jenis": "Individu",
      "nama": "NAMA LENGKAP",
      "nama_alias": ["ALIAS"],
      "kategori": "DTTOT",
      "dasar_penetapan": "Keputusan BNPT No. 123/2024",
      "tanggal_penetapan": "2024-03-01",
      "status": "AKTIF",
      "daftar_asal": "Domestik - BNPT"
    }
  ]
}
```

### SIPP Litigasi JSON (manual override)

```json
[
  {
    "nomor_perkara": "412/Pdt.G/2024/PN.Jkt.Bar",
    "klasifikasi": "Wanprestasi Kontrak",
    "pemohon": "PT MAJU SENTOSA",
    "termohon": "PT NAMA PERUSAHAAN",
    "status_perkara": "Selesai - Mediasi Berhasil",
    "tanggal_register": "15 Maret 2024",
    "nilai_gugatan": "Rp. 2,500,000,000"
  }
]
```

---

## Output

Hasil disimpan di folder `output/`:

```
output/
├── NAMA_PERUSAHAAN_YYYYMMDD_HHMMSS.json   ← profil + risk assessment
└── NAMA_PERUSAHAAN_YYYYMMDD_HHMMSS.pdf    ← laporan PDF
```

### Contoh Output JSON

```json
{
  "isProfileComplete": true,
  "company": { "name": "ANEKA BINTANG GADING", "status": "TERTUTUP" },
  "shareholders": ["..."],
  "companyGoals": ["..."],
  "risk_assessment": {
    "overall_risk_score": 65,
    "risk_classification": "Moderate-High Risk",
    "regulatory_recommendation": "Enhanced Due Diligence (EDD) Required",
    "ubo_analysis": { "has_ubo_above_threshold": true },
    "litigation_summary": { "total_cases": 1 },
    "key_findings": ["Ivan Tanjaya (24.32%) terdeteksi dalam kasus wanprestasi"]
  },
  "internet_research": { "overall_internet_risk": "Flag for Review" }
}
```

---

## Risk Scoring

| Skor | Klasifikasi | Rekomendasi |
|---|---|---|
| 1–25 | Low Risk | Setujui |
| 26–50 | Moderate Risk | Setujui dengan Monitoring |
| 51–75 | Moderate-High Risk | Enhanced Due Diligence (EDD) Required |
| 76–100 | High Risk | Tolak / Eskalasi ke Komite |

**Faktor penambah skor:**

| Faktor | Poin |
|---|---|
| UBO ≥25% | +15 |
| Litigasi aktif | +20 |
| Litigasi selesai | +10 |
| KBLI berisiko tinggi (kelab malam, bar, alkohol) | +15 |
| Badan hukum pemegang saham tanpa transparansi | +10 |
| PPATK DTTOT aktif (domestik) | +40 |
| PPATK TPPU | +20 |
| Sanksi internasional (OFAC / UN SC) | +30 |
| Adverse media — High | +20 |
| Adverse media — Medium | +10 |
| PEP terdeteksi | +15 |

---

## Struktur Proyek

```
customer-profiling-ai/
├── run_pipeline.py              ← Entry point utama
├── requirements.txt
├── .env                         ← API key (jangan di-commit)
│
├── src/
│   ├── agents/
│   │   ├── graph.py             ← AgenticWorkflow orchestrator
│   │   └── nodes.py             ← Researcher, Drafter, Critic agents
│   ├── core/
│   │   ├── config.py            ← Config (API key, DB path, model names)
│   │   └── state.py             ← PipelineState + semua Pydantic models
│   ├── tools/
│   │   ├── scraper.py           ← DB manager + SIPP web scraper
│   │   ├── ahu_scraper.py       ← AHUScraperTool (query DB)
│   │   ├── ppatk_tool.py        ← PPATKTool (screening DTTOT)
│   │   ├── sipp_scraper.py      ← SIPPScraperTool (query DB)
│   │   ├── internet_researcher.py ← Google Search Grounding
│   │   ├── report_generator.py  ← JSON + PDF output
│   │   └── README_SCRAPER.md    ← Dokumentasi scraper & DB manager
│   └── validation/
│       └── hcat_tester.py       ← HCAT shadow evaluation
│
├── output/                      ← JSON + PDF hasil profiling
├── validation_reports/          ← Laporan HCAT
└── kyb_internal.db              ← Internal database (auto-created)
```

---

## Regulasi & Kepatuhan

| Regulasi | Relevansi |
|---|---|
| POJK No. 12/POJK.01/2017 | Kewajiban KYC/CDD bagi Lembaga Jasa Keuangan |
| UU No. 8 Tahun 2010 | Pencegahan dan Pemberantasan TPPU |
| Peraturan PPATK No. 2 Tahun 2023 | Targeted Financial Sanctions (DTTOT) |
| Perpres No. 13 Tahun 2018 | Penerapan Prinsip Mengenali Pemilik Manfaat (UBO) |
| UU No. 37 Tahun 2004 | Kepailitan dan PKPU |

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'bs4'`**
```bash
# Aktifkan venv terlebih dahulu, lalu jalankan:
.venv\Scripts\activate
python src/tools/scraper.py --load-ahu ...
```

**`GEMINI_API_KEY tidak ditemukan`**
```bash
# Pastikan file .env ada dan terisi dengan benar
```

**Data AHU tidak ditemukan saat pipeline berjalan**
```bash
# Import dulu ke DB sebelum menjalankan pipeline:
python src/tools/scraper.py --load-ahu "path/to/ahu_data.json"
```

**SIPP tidak ada data (0 kasus litigasi)**
```bash
# Scrape dari web terlebih dahulu:
python src/tools/scraper.py --court surabaya
# Atau upload manual saat pipeline Mode 2
```
