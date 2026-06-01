from src.core.state import PipelineState
from src.agents.nodes import (
    researcher_agent, internet_research_agent,
    drafter_agent, critic_agent
)
from src.tools.report_generator import ReportGenerator


class AgenticWorkflow:
    """
    Multi-Agent Agentic Workflow untuk Customer Profiling AI-KYB.
    
    Pipeline (Updated):
    1. Researcher Agent → mengumpulkan data mentah dari AHU + SIPP
    2. Internet Research Agent → riset internet (adverse media, sanctions, PEP)
    3. Drafter Agent → menyusun profil terstruktur + risk assessment 
    4. Critic Agent → validasi guardrails (self-correction loop)
    5. Output Generation → simpan JSON + generate PDF report
    """

    def __init__(self, max_revisions: int = 3):
        self.max_revisions = max_revisions

    def run(self, company_name: str, nib: str = None, state: PipelineState = None) -> PipelineState:
        """
        Menjalankan pipeline profiling.
        
        Args:
            company_name: Nama perusahaan target
            nib: Nomor Induk Berusaha (opsional)
            state: PipelineState yang sudah ada (untuk manual upload mode)
        
        Returns:
            PipelineState final
        """
        if state is None:
            state = PipelineState(company_name=company_name, nib=nib)

        # Step 1: Research - mengumpulkan data mentah
        print("\n" + "=" * 60)
        print("📡 FASE 1: DATA COLLECTION (Researcher Agent)")
        print("=" * 60)
        state = researcher_agent(state)

        if "error" in state.raw_ahu_data:
            print(f"\n❌ PIPELINE BERHENTI: Data AHU tidak ditemukan untuk '{company_name}'")
            return state

        # Step 2: Internet Research (NEW)
        print("\n" + "=" * 60)
        print("🌐 FASE 2: INTERNET RESEARCH (Internet Research Agent)")
        print("=" * 60)
        state = internet_research_agent(state)

        # Step 3 & 4: Draft + Critique (Self-Correction Loop / Reflexion)
        print("\n" + "=" * 60)
        print("🔄 FASE 3: PROFILING & RISK ASSESSMENT (Drafter ↔ Critic Loop)")
        print("=" * 60)

        while not state.is_valid and state.revision_count < self.max_revisions:
            state = drafter_agent(state)
            state = critic_agent(state)
            if not state.is_valid:
                state.revision_count += 1
                print(f"\n   🔄 Memulai revisi ke-{state.revision_count}...")

        if not state.is_valid:
            print("\n⚠️ PERINGATAN: Batas maksimal revisi (3) tercapai. Dibutuhkan peninjauan manusia.")
            print("   Profil terakhir akan tetap disimpan untuk review manual.")

        # Step 5: Output Generation
        if state.company_profile:
            print("\n" + "=" * 60)
            print("💾 FASE 4: OUTPUT GENERATION")
            print("=" * 60)
            
            # Simpan JSON
            state.json_output_path = ReportGenerator.save_json(state.company_profile)
            
            # Generate PDF Report
            state.pdf_output_path = ReportGenerator.generate_pdf(state.company_profile)

        return state