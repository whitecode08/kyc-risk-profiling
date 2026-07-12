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
# NOTE: The anthropic Python SDK reads ANTHROPIC_API_KEY by default.
# OpenModel.ai uses ANTHROPIC_AUTH_TOKEN (same value). We export both
# so the Anthropic() client can be initialized explicitly in each module.

GOOGLE_SEARCH_ENGINE_ID = os.getenv("SEARCH_ENGINE_ID", "")

# ANTHROPIC_AUTH_TOKEN is the OpenModel token (om-xxxx).
# We expose it as ANTHROPIC_API_KEY so the SDK picks it up correctly.
ANTHROPIC_API_KEY = (
    os.getenv("ANTHROPIC_AUTH_TOKEN") or
    os.getenv("ANTHROPIC_API_KEY") or
    ""
)
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.openmodel.ai")

if not ANTHROPIC_API_KEY:
    raise ValueError(
        "ANTHROPIC_AUTH_TOKEN tidak ditemukan di file .env. "
        "Harap isi terlebih dahulu."
    )

# ─── Model Selection ─────────────────────────────────────────────────────────

HEAVY_IO_MODEL = os.getenv("ANTHROPIC_MODEL", os.getenv("HEAVY_IO_MODEL", "deepseek-v4-flash"))
COMPLEX_REASONING_MODEL = os.getenv("ANTHROPIC_MODEL", os.getenv("COMPLEX_REASONING_MODEL", "deepseek-v4-flash"))

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


# ─── LLM Response Helper ──────────────────────────────────────────────────────

def extract_text_from_response(response) -> str:
    """
    Safely extract the text content from an Anthropic API response.

    Models like deepseek-v4 (with reasoning/thinking enabled) may return
    a ThinkingBlock as the first content block before the actual TextBlock.
    Using response.content[0].text directly will raise AttributeError in
    that case. This helper scans all blocks and returns the first one that
    has a .text attribute (i.e. the real TextBlock).

    Args:
        response: Anthropic Message response object

    Returns:
        str: The text content from the first TextBlock found, or fallback to thinking block

    Raises:
        ValueError: If no text can be extracted or if the response was truncated
    """
    # 1. Try to get the actual TextBlock
    for block in response.content:
        if hasattr(block, "text") and block.text.strip():
            return block.text
            
    # 2. Check if we hit token limit before outputting text
    if getattr(response, "stop_reason", None) == "max_tokens":
        raise ValueError("Response truncated (stop_reason=max_tokens) sebelum mengeluarkan teks output. "
                         "Pertimbangkan menambah max_tokens atau menginstruksikan LLM agar lebih ringkas.")

    # 3. Fallback: if it only outputted thinking and stopped normally
    for block in response.content:
        if hasattr(block, "thinking") and block.thinking.strip():
            return block.thinking

    raise ValueError(
        f"No text could be extracted. "
        f"Block types: {[type(b).__name__ for b in response.content]}"
    )
