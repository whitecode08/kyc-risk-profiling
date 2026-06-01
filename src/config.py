"""
KYB Intelligence Pipeline — Configuration
==========================================
Load environment variables dan risk weight configuration.
"""

import os
import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ─── Paths ────────────────────────────────────────────────────────────────────

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
INPUT_DIR = DATA_DIR / "input"
OUTPUT_DIR = DATA_DIR / "output"
WEIGHT_DIR = DATA_DIR / "weight"
TEMPLATE_DIR = ROOT_DIR / "templates"
SUMMARY_DIR = ROOT_DIR / "summary"

# Ensure output directories exist
(OUTPUT_DIR / "sipp_scraped").mkdir(parents=True, exist_ok=True)
(OUTPUT_DIR / "internet_osint").mkdir(parents=True, exist_ok=True)
(SUMMARY_DIR / "json").mkdir(parents=True, exist_ok=True)
(SUMMARY_DIR / "pdf").mkdir(parents=True, exist_ok=True)

# ─── API Keys ─────────────────────────────────────────────────────────────────

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GOOGLE_SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID", "")

if not GEMINI_API_KEY:
    raise ValueError(
        "GEMINI_API_KEY tidak ditemukan di file .env. "
        "Harap isi terlebih dahulu."
    )

# ─── Model Selection ─────────────────────────────────────────────────────────

HEAVY_IO_MODEL = os.getenv("HEAVY_IO_MODEL", "gemini-2.5-flash")
COMPLEX_REASONING_MODEL = os.getenv("COMPLEX_REASONING_MODEL", "gemini-2.5-flash")

# ─── Risk Weights ─────────────────────────────────────────────────────────────

def _load_risk_weights() -> dict:
    """Load risk weights dari file JSON."""
    weights_path = WEIGHT_DIR / "risk_weights.json"
    try:
        with open(weights_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {
            "dimensions": {
                "Ownership_and_Industry_Risk": {"base_weight": 20, "max_score": 25},
                "AML_Risk": {"base_weight": 40, "max_score": 50},
                "Legal_Risk": {"base_weight": 15, "max_score": 20},
                "Reputation_Risk": {"base_weight": 15, "max_score": 20},
            },
            "ubo_threshold_pct": 25.0,
        }

RISK_WEIGHTS = _load_risk_weights()
