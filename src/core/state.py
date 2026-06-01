from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum


class InputMode(str, Enum):
    """Mode input data untuk pipeline."""
    NIB_LOOKUP = "nib_lookup"        # Lookup via NIB + Nama Perusahaan
    MANUAL_UPLOAD = "manual_upload"  # Upload PDF/JSON manual


# ============================================================
# Sub-Models untuk struktur JSON output (sesuai skema contoh)
# ============================================================

class CompanyInfo(BaseModel):
    """Informasi dasar perusahaan dari AHU."""
    name: str = Field(default="", description="Nama lengkap perusahaan")
    shortName: str = Field(default="", description="Nama singkat")
    skNumber: str = Field(default="", description="Nomor SK Pengesahan")
    skDate: str = Field(default="", description="Tanggal SK")
    spNumber: str = Field(default="", description="Nomor SP")
    spDate: str = Field(default="", description="Tanggal SP")
    companySpNumber: str = Field(default="", description="Nomor SP Perusahaan")
    companySpDate: str = Field(default="", description="Tanggal SP Perusahaan")
    type: str = Field(default="", description="Jenis perusahaan (PMDN/PMA)")
    timePeriod: str = Field(default="", description="Jangka waktu pendirian")
    status: str = Field(default="", description="Status perusahaan (TERBUKA/TERTUTUP)")
    phoneNo: str = Field(default="", description="Nomor telepon")
    transactionType: str = Field(default="", description="Jenis transaksi (PENDIRIAN/PERUBAHAN)")


class CompanyAddress(BaseModel):
    """Alamat perusahaan."""
    address: str = Field(default="", description="Alamat jalan")
    rt: str = Field(default="0", description="RT")
    rw: str = Field(default="0", description="RW")
    postalCode: str = Field(default="", description="Kode pos")
    ward: str = Field(default="", description="Kelurahan")
    subdistrict: str = Field(default="", description="Kecamatan")
    regency: str = Field(default="", description="Kota/Kabupaten")
    province: str = Field(default="", description="Provinsi")


class CompanyGoal(BaseModel):
    """Maksud dan tujuan perusahaan (KBLI)."""
    no: int = Field(description="Nomor urut")
    code: str = Field(description="Kode KBLI")
    name: str = Field(description="Nama kegiatan usaha")
    description: str = Field(default="", description="Deskripsi kegiatan usaha")


class NotaryInfo(BaseModel):
    """Informasi notaris."""
    name: str = Field(default="", description="Nama notaris")
    shortAddress: str = Field(default="", description="Alamat singkat notaris")
    deedNumber: str = Field(default="", description="Nomor akta")
    deedDate: str = Field(default="", description="Tanggal akta")


class StockInfo(BaseModel):
    """Informasi modal/saham."""
    classification: str = Field(default="", description="Klasifikasi saham")
    pricePerShare: str = Field(default="", description="Nilai nominal per saham")
    numberOfShares: str = Field(default="", description="Jumlah saham")
    grandTotal: str = Field(default="", description="Total nilai")


class ShareholderInfo(BaseModel):
    """Informasi pemegang saham / pengurus."""
    name: str = Field(description="Nama pemegang saham")
    passport: str = Field(default="", description="Nomor KTP/Paspor")
    country: str = Field(default="Indonesia", description="Negara asal")
    kitas: str = Field(default="", description="Nomor KITAS")
    ttl: str = Field(default="-, -", description="Tempat/tanggal lahir")
    position: str = Field(default="-", description="Jabatan dalam perusahaan")
    address: str = Field(default="", description="Alamat")
    classification: str = Field(default="", description="Klasifikasi saham")
    numberOfShares: str = Field(default="0", description="Jumlah saham dimiliki")
    grandTotal: str = Field(default="Rp. 0", description="Nilai total saham")


# ============================================================
# Risk Assessment Models
# ============================================================

class UBODetail(BaseModel):
    name: str = Field(default="", description="Nama UBO")
    percentage: float = Field(default=0.0, description="Persentase kepemilikan")
    position: str = Field(default="-", description="Jabatan")

class UBOAnalysis(BaseModel):
    """Analisis Ultimate Beneficial Owner."""
    identified_ubos: List[UBODetail] = Field(
        default_factory=list,
        description="Daftar UBO yang teridentifikasi (nama, persentase, posisi)"
    )
    ubo_threshold_pct: float = Field(default=25.0, description="Threshold UBO dalam persen")
    has_ubo_above_threshold: bool = Field(default=False, description="Ada UBO di atas threshold")


class LitigationCase(BaseModel):
    nomor_perkara: str = Field(default="", description="Nomor perkara")
    klasifikasi: str = Field(default="", description="Klasifikasi perkara")
    status: str = Field(default="", description="Status perkara")

class LitigationSummary(BaseModel):
    """Ringkasan litigasi dari SIPP."""
    total_cases: int = Field(default=0, description="Total kasus litigasi")
    cases: List[LitigationCase] = Field(default_factory=list, description="Detail kasus")
    has_active_litigation: bool = Field(default=False, description="Ada litigasi aktif")


class RiskAssessment(BaseModel):
    """Penilaian risiko komprehensif."""
    overall_risk_score: int = Field(default=0, description="Skor risiko 1-100")
    risk_classification: str = Field(
        default="Low Risk",
        description="Low Risk / Moderate Risk / Moderate-High Risk / High Risk"
    )
    ubo_analysis: UBOAnalysis = Field(default_factory=UBOAnalysis)
    litigation_summary: LitigationSummary = Field(default_factory=LitigationSummary)
    key_findings: List[str] = Field(
        default_factory=list,
        description="Temuan utama dari analisis risiko"
    )
    regulatory_recommendation: str = Field(
        default="",
        description="Rekomendasi: Setujui / Tolak / Enhanced Due Diligence (EDD) Required"
    )


# ============================================================
# Internet Research Models (OSINT dari Google Search)
# ============================================================

class AdverseMediaHit(BaseModel):
    """Temuan berita negatif/adverse media dari internet."""
    entity_name: str = Field(default="", description="Nama entitas terkait")
    headline: str = Field(default="", description="Judul berita/temuan")
    summary: str = Field(default="", description="Ringkasan temuan")
    source: str = Field(default="", description="Sumber (URL/nama media)")
    severity: str = Field(default="Low", description="Low / Medium / High")
    relevance_score: float = Field(default=0.0, description="Skor relevansi 0-1")


class SanctionsScreening(BaseModel):
    """Hasil screening daftar sanksi internasional."""
    entity_name: str = Field(default="", description="Nama entitas yang dicek")
    is_sanctioned: bool = Field(default=False, description="Ada di daftar sanksi")
    sanction_lists_checked: List[str] = Field(
        default_factory=lambda: ["OFAC SDN", "UN Security Council", "EU Sanctions", "PPATK DTTOT"],
        description="Daftar sanksi yang dicek"
    )
    matches_found: List[str] = Field(default_factory=list, description="Daftar kecocokan yang ditemukan")
    screening_notes: str = Field(default="", description="Catatan screening")


class PEPFlag(BaseModel):
    """Flag Politically Exposed Person."""
    name: str = Field(default="", description="Nama individu")
    is_pep: bool = Field(default=False, description="Teridentifikasi sebagai PEP")
    pep_category: str = Field(default="", description="Kategori PEP (legislatif/eksekutif/yudikatif)")
    details: str = Field(default="", description="Detail posisi/jabatan politik")


class InternetResearchResult(BaseModel):
    """Hasil riset internet komprehensif."""
    adverse_media: List[AdverseMediaHit] = Field(default_factory=list)
    sanctions_screening: List[SanctionsScreening] = Field(default_factory=list)
    pep_flags: List[PEPFlag] = Field(default_factory=list)
    business_legitimacy_notes: str = Field(default="", description="Catatan verifikasi legitimasi bisnis")
    overall_internet_risk: str = Field(
        default="Clean",
        description="Clean / Flag for Review / High Risk"
    )
    search_queries_used: List[str] = Field(default_factory=list, description="Query pencarian yang digunakan")
    raw_search_summary: str = Field(default="", description="Ringkasan mentah dari hasil pencarian")


# ============================================================
# Main Output Model (JSON Database)
# ============================================================

class CompanyProfileOutput(BaseModel):
    """Model output JSON final - sesuai skema contoh ANEKA BINTANG GADING.json"""
    isProfileComplete: bool = Field(default=False, description="Apakah profil lengkap")
    company: CompanyInfo = Field(default_factory=CompanyInfo)
    companyAddress: CompanyAddress = Field(default_factory=CompanyAddress)
    companyGoals: List[CompanyGoal] = Field(default_factory=list)
    notary: NotaryInfo = Field(default_factory=NotaryInfo)
    baseStock: StockInfo = Field(default_factory=StockInfo)
    issuedStock: StockInfo = Field(default_factory=StockInfo)
    paidUpStock: str = Field(default="", description="Modal disetor")
    shareholders: List[ShareholderInfo] = Field(default_factory=list)
    risk_assessment: RiskAssessment = Field(default_factory=RiskAssessment)
    internet_research: Optional[InternetResearchResult] = Field(
        default=None,
        description="Hasil riset internet (adverse media, sanctions, PEP)"
    )


# ============================================================
# Critic Feedback Model (untuk self-correction loop)
# ============================================================

class CriticFeedback(BaseModel):
    is_valid: bool = Field(description="True jika laporan memenuhi semua guardrails, False jika ada yang kurang")
    feedback: str = Field(description="Kritik detail mengenai apa yang harus diperbaiki oleh Drafter")
    missing_fields: List[str] = Field(
        default_factory=list,
        description="Field yang masih kosong atau belum terisi"
    )


# ============================================================
# Pipeline State (state graph untuk multi-agent workflow)
# ============================================================

class PipelineState(BaseModel):
    company_name: str
    # Anti-Bias Anchor Parameters (dikunci di awal per TSD)
    nib: Optional[str] = Field(default=None, description="Nomor Induk Berusaha (anchor parameter)")
    input_mode: InputMode = Field(default=InputMode.NIB_LOOKUP, description="Mode input data")
    anchor_locked: bool = Field(default=False, description="Parameter sudah dikunci (anti-bias)")
    # Raw data dari sumber
    raw_ahu_data: Dict[str, Any] = {}
    raw_sipp_data: List[Dict[str, Any]] = []
    # PPATK DTTOT screening results
    raw_ppatk_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Hasil screening PPATK DTTOT: {total_checked, total_hits, has_active_sanctions, hits, ...}"
    )
    # Internet research results
    internet_research: Optional[InternetResearchResult] = None
    # Structured output
    company_profile: Optional[CompanyProfileOutput] = None
    # Validation state
    is_valid: bool = False
    critic_feedback: str = ""
    missing_fields: List[str] = []
    revision_count: int = 0
    # Output paths
    json_output_path: str = ""
    pdf_output_path: str = ""