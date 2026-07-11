# AI-KYB Customer Profiling System

**Autonomous Intelligence Pipeline untuk Know Your Business (KYB) & Anti-Money Laundering (AML)**

Sistem profiling perusahaan berbasis AI yang mengotomasi pengumpulan, analisis, dan penilaian risiko nasabah korporat — sesuai regulasi OJK, PPATK, dan standar FATF.

---

## Fitur Utama

- **Data AHU & PPATK Ingestion** — Otomatis memproses JSON profil perusahaan dan entitas sanksi dari `data/input/`
- **UBO Extraction** — Otomatis mendeteksi Top 5 Ultimate Beneficial Owners berdasarkan persentase kepemilikan saham
- **SIPP Litigasi Scraping** — Mencari kasus hukum terkait perusahaan & UBO
- **Internet OSINT** — Mencari adverse media, PEP (Politically Exposed Persons), dan sanksi global secara dinamis
- **Agentic Fusion & Risk Scoring** — Menghitung risk score, level kontaminasi, dan rekomendasi secara deterministik
- **PDF Report Generation** — Export otomatis profil perusahaan dalam bentuk JSON maupun Intelligence Report PDF

---

## Arsitektur Pipeline

```
┌─────────────────── DATA SOURCES ───────────────────────┐
│  AHU JSON       PPATK JSON         SIPP Web (scraped)  │
│  (data/input)   (data/input)                           │
└───────────────┬───────┬───────────────────┬────────────┘
                ▼       ▼                   ▼
      ┌─────────────────────────────────────────┐
      │  FASE 1: Data Ingestion                 │
      │  · Load AHU & Extract UBO               │
      │  · Screen PPATK (Corporate + UBO)       │
      └─────────────────┬───────────────────────┘
                        ▼
      ┌─────────────────────────────────────────┐
      │  FASE 2: SIPP Scraping                  │
      │  · Litigasi Perusahaan & Pengurus       │
      └─────────────────┬───────────────────────┘
                        ▼
      ┌─────────────────────────────────────────┐
      │  FASE 3: OSINT Research                 │
      │  · Adverse media & Sanctions            │
      └─────────────────┬───────────────────────┘
                        ▼
      ┌─────────────────────────────────────────┐
      │  FASE 4: Agentic Fusion & Risk Scoring  │
      │  · Structured risk assessment           │
      │  · Risk calculation                     │
      └─────────────────┬───────────────────────┘
                        ▼
      ┌─────────────────────────────────────────┐
      │  FASE 5: Report Generation              │
      │  · JSON output (summary/json/)          │
      │  · PDF report (summary/pdf/)            │
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
cd kyc-risk-profiling

# 2. Buat virtual environment
python -m venv .venv

# 3. Aktifkan venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Konfigurasi API key — copy .env.example menjadi .env dan isi API Key
```

### Konfigurasi `.env`

```env
GEMINI_API_KEY="your-gemini-api-key-here"
```

---

## Cara Penggunaan

### Step 1 — Siapkan Data Input

Letakkan file data di dalam folder `data/input/`:
1. File AHU perusahaan diletakkan di folder `data/input/ahu/` (format `.json`)
2. File daftar sanksi PPATK diletakkan di folder `data/input/ppatk/` (format `.json`)

### Step 2 — Jalankan Pipeline

Jalankan script eksekusi utama:
```bash
python run_pipeline.py
```

Anda akan disajikan menu interaktif:
```
📋 PILIH MODE INPUT DATA:
────────────────────────────────────────────
  [1] Cari nama perusahaan di folder data/input/ahu/
  [2] Input path file JSON AHU
────────────────────────────────────────────

🔹 Pilih mode (1/2): 1

   📋 Perusahaan tersedia:
      1. 01__ahu__aneka_bintang_gading

   Nama perusahaan: ANEKA BINTANG GADING
```

Atau gunakan **Mode CLI (Bypass Menu)**:
```bash
python run_pipeline.py --json data/input/ahu/01__ahu__aneka_bintang_gading.json
python run_pipeline.py --company "ANEKA BINTANG GADING" --nib 1234567890
```

---

## Output

Hasil investigasi akan disimpan di dalam folder root `summary/`:
- **`summary/json/`** : Hasil investigasi (raw data dan AI scoring) berformat JSON
- **`summary/pdf/`**  : Hasil Intelligence Report yang siap dicetak berformat PDF

*Data scraping (OSINT dan SIPP) akan disimpan ke dalam folder sementara `data/output/` sebagai cache untuk mencegah panggilan berulang.*

---

## Format Data (Input)

### AHU JSON

Contoh struktur skema data AHU yang diperlukan:

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
      "status": "AKTIF",
      "daftar_asal": "Domestik - BNPT"
    }
  ]
}
```

---

## Struktur Proyek

```
kyc-risk-profiling/
├── run_pipeline.py              ← Main execution entry point
├── requirements.txt
├── .env                         ← File environment (API keys)
├── data/
│   ├── input/
│   │   ├── ahu/                 ← Folder JSON input AHU
│   │   └── ppatk/               ← Folder JSON input PPATK
│   ├── output/                  ← Data scraper hasil cache
│   │   ├── internet_osint/
│   │   └── sipp_scraped/
│   └── weight/
│       └── risk_weights.json    ← Konfigurasi bobot penilaian otomatis
├── src/
│   ├── config.py                ← Konfigurasi directory system
│   ├── data_ingestion.py        ← Membaca & parsing file AHU, UBO, PPATK
│   ├── reporting.py             ← Menyimpan JSON dan rendering HTML to PDF
│   ├── agents/                  
│   │   ├── fusion_agent.py      ← Agent Risk Scoring & Aggregation
│   │   └── hcat_evaluator.py    
│   └── scrapers/                
│       ├── osint_researcher.py  ← Agent Web Search untuk OSINT
│       └── sipp_scraper.py      ← Agent scraping SIPP litigasi
├── summary/                     ← Folder Hasil Laporan Terakhir
│   ├── json/
│   └── pdf/
└── templates/                   
    └── report_template.html     ← Template desain laporan HTML (PDF base)
```

---

## Regulasi & Kepatuhan

| Regulasi | Relevansi |
|---|---|
| POJK No. 12/POJK.01/2017 | Kewajiban KYC/CDD bagi Lembaga Jasa Keuangan |
| Peraturan PPATK No. 2 Tahun 2023 | Targeted Financial Sanctions (DTTOT) |
| Perpres No. 13 Tahun 2018 | Penerapan Prinsip Mengenali Pemilik Manfaat (UBO) |
