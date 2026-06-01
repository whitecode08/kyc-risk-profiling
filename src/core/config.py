import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    HEAVY_IO_MODEL = os.getenv("HEAVY_IO_MODEL", "gemini-2.5-flash")
    COMPLEX_REASONING_MODEL = os.getenv("COMPLEX_REASONING_MODEL", "gemini-2.5-flash")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")

    # Shared internal database path (AHU + PPATK + SIPP all stored here)
    DB_PATH = os.getenv("DB_PATH", "kyb_internal.db")

    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY tidak ditemukan di file .env. Harap isi terlebih dahulu.")