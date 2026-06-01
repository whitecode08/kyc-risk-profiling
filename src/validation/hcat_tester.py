import numpy as np
from google import genai
from src.core.config import Config
import json
import os
import time


class HCATStatisticalTester:
    """
    Human-Calibrated Automated Testing (HCAT) Framework.
    
    Implementasi berdasarkan paper "HCAT - AI Validation" yang mencakup 4 metrik:
    1. Context Relevancy  — seberapa relevan konteks sumber terhadap query
    2. Groundedness       — seberapa grounded jawaban AI pada konteks sumber  
    3. Completeness       — seberapa lengkap jawaban AI mencakup informasi konteks
    4. Answer Relevancy   — seberapa relevan jawaban terhadap pertanyaan/tujuan
    
    Menggunakan sentence-level embedding comparison dengan cosine similarity
    dan Wasserstein Distance untuk completeness (sesuai paper).
    """

    def __init__(self):
        self.client = genai.Client(api_key=Config.GEMINI_API_KEY)
        self.embedding_model = Config.EMBEDDING_MODEL

    def _get_embedding(self, text: str) -> list:
        """Dapatkan embedding vektor dari teks menggunakan Gemini Embedding Model."""
        # Truncate teks yang terlalu panjang untuk embedding
        max_chars = 2000
        if len(text) > max_chars:
            text = text[:max_chars]

        for attempt in range(3):
            try:
                response = self.client.models.embed_content(
                    model=self.embedding_model,
                    contents=text
                )
                return response.embeddings[0].values
            except Exception as e:
                if attempt < 2:
                    print(f"   [!] Embedding retry ({attempt + 1}/3): {e}")
                    time.sleep(2)
                else:
                    print(f"   [!] Embedding gagal setelah 3 percobaan: {e}")
                    return []

    def _get_embeddings_batch(self, texts: list) -> list:
        """Dapatkan embeddings untuk banyak teks sekaligus."""
        embeddings = []
        for text in texts:
            emb = self._get_embedding(text)
            if emb:
                embeddings.append(emb)
            time.sleep(0.1)  # Rate limiting
        return embeddings

    def _cosine_similarity(self, vec_a, vec_b) -> float:
        """Hitung cosine similarity antara dua vektor."""
        if not vec_a or not vec_b:
            return 0.0
        vec_a = np.array(vec_a)
        vec_b = np.array(vec_b)
        dot_product = np.dot(vec_a, vec_b)
        norm_a = np.linalg.norm(vec_a)
        norm_b = np.linalg.norm(vec_b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot_product / (norm_a * norm_b))

    def _split_to_sentences(self, text: str) -> list:
        """Pecah teks menjadi kalimat-kalimat (sentence-level per paper HCAT)."""
        if not text:
            return []
        # Split by common sentence delimiters
        import re
        sentences = re.split(r'[.!?\n]+', text)
        # Filter kalimat kosong dan terlalu pendek
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        return sentences

    # ================================================================
    # METRIK 1: CONTEXT RELEVANCY (Section 3.1 Paper HCAT)
    # ================================================================
    def calculate_context_relevancy(self, query_sentences: list, context_sentences: list) -> float:
        """
        Mengukur seberapa relevan konteks yang di-retrieve terhadap query.
        
        Formula (per paper):
        S_max(q_i) = max_{1≤j≤n} Sim(q_i, c_j) untuk setiap kalimat query
        S_c-relevancy = (1/m) * Σ S_max(q_i)
        """
        if not query_sentences or not context_sentences:
            return 0.0

        q_embeddings = self._get_embeddings_batch(query_sentences)
        c_embeddings = self._get_embeddings_batch(context_sentences)

        if not q_embeddings or not c_embeddings:
            return 0.0

        max_similarities = []
        for q_vec in q_embeddings:
            sims = [self._cosine_similarity(q_vec, c_vec) for c_vec in c_embeddings]
            max_similarities.append(max(sims) if sims else 0.0)

        return float(np.mean(max_similarities))

    # ================================================================
    # METRIK 2: GROUNDEDNESS (Section 3.2 Paper HCAT)
    # ================================================================
    def calculate_groundedness(self, answer_sentences: list, context_sentences: list) -> float:
        """
        Mengukur apakah jawaban AI di-ground pada konteks sumber.
        
        Formula (per paper):
        S_max(a_i) = max_{1≤j≤n} Sim(a_i, c_j) untuk setiap kalimat jawaban
        S_groundedness = (1/k) * Σ S_max(a_i)
        
        Skor tinggi = jawaban berdasarkan data sumber (bukan halusinasi)
        """
        if not answer_sentences or not context_sentences:
            return 0.0

        a_embeddings = self._get_embeddings_batch(answer_sentences)
        c_embeddings = self._get_embeddings_batch(context_sentences)

        if not a_embeddings or not c_embeddings:
            return 0.0

        max_similarities = []
        for a_vec in a_embeddings:
            sims = [self._cosine_similarity(a_vec, c_vec) for c_vec in c_embeddings]
            max_similarities.append(max(sims) if sims else 0.0)

        return float(np.mean(max_similarities))

    # ================================================================
    # METRIK 3: COMPLETENESS (Section 3.3 Paper HCAT)
    # ================================================================
    def calculate_completeness(self, answer_sentences: list, context_sentences: list) -> dict:
        """
        Mengukur apakah jawaban mencakup seluruh informasi dari konteks.
        
        Dua pendekatan per paper HCAT:
        
        A) Sentence Similarity (Section 3.3.1):
           S_max(c_i) = max_{1≤j≤k} Sim(c_i, a_j) untuk setiap kalimat konteks
           S_completeness = (1/n) * Σ S_max(c_i)
        
        B) Wasserstein Distance (Section 3.3.2):
           W(C, A) = (1/nk) * Σ_i Σ_j d(c_i, a_j)
           Completeness_W = 1 - W(C, A)
        """
        if not answer_sentences or not context_sentences:
            return {"sentence_similarity": 0.0, "wasserstein": 0.0, "combined": 0.0}

        c_embeddings = self._get_embeddings_batch(context_sentences)
        a_embeddings = self._get_embeddings_batch(answer_sentences)

        if not c_embeddings or not a_embeddings:
            return {"sentence_similarity": 0.0, "wasserstein": 0.0, "combined": 0.0}

        # A) Sentence Similarity Approach
        max_similarities = []
        for c_vec in c_embeddings:
            sims = [self._cosine_similarity(c_vec, a_vec) for a_vec in a_embeddings]
            max_similarities.append(max(sims) if sims else 0.0)
        sentence_sim_score = float(np.mean(max_similarities))

        # B) Wasserstein Distance Approach (simplified uniform weighting per paper)
        n = len(c_embeddings)
        k = len(a_embeddings)
        total_cost = 0.0
        for c_vec in c_embeddings:
            for a_vec in a_embeddings:
                cosine_dist = 1.0 - self._cosine_similarity(c_vec, a_vec)
                total_cost += cosine_dist
        wasserstein_distance = total_cost / (n * k)
        wasserstein_score = float(1.0 - wasserstein_distance)

        # Combined (average of both approaches per paper recommendation)
        combined = float((sentence_sim_score + wasserstein_score) / 2)

        return {
            "sentence_similarity": round(sentence_sim_score, 4),
            "wasserstein": round(wasserstein_score, 4),
            "combined": round(combined, 4)
        }

    # ================================================================
    # METRIK 4: ANSWER RELEVANCY (Section 3.4 Paper HCAT)
    # ================================================================
    def calculate_answer_relevancy(self, answer_sentences: list, query_sentences: list) -> float:
        """
        Mengukur seberapa relevan jawaban terhadap pertanyaan/tujuan awal.
        
        Formula (per paper):
        S_max(a_i) = max_{1≤j≤m} Sim(a_i, q_j) untuk setiap kalimat jawaban
        S_a-relevancy = (1/k) * Σ S_max(a_i)
        """
        if not answer_sentences or not query_sentences:
            return 0.0

        a_embeddings = self._get_embeddings_batch(answer_sentences)
        q_embeddings = self._get_embeddings_batch(query_sentences)

        if not a_embeddings or not q_embeddings:
            return 0.0

        max_similarities = []
        for a_vec in a_embeddings:
            sims = [self._cosine_similarity(a_vec, q_vec) for q_vec in q_embeddings]
            max_similarities.append(max(sims) if sims else 0.0)

        return float(np.mean(max_similarities))

    # ================================================================
    # MAIN EVALUATION RUNNER
    # ================================================================
    def run_shadow_evaluation(self, raw_data_texts: list, ai_report: dict) -> dict:
        """
        Menjalankan evaluasi HCAT lengkap (4 metrik) sebagai shadow/observer.
        
        Args:
            raw_data_texts: List teks data mentah (konteks sumber)
            ai_report: Dict hasil laporan AI (company profile + risk assessment)
        
        Returns:
            Dict berisi semua metrik HCAT dan assessment
        """
        print("\n" + "=" * 60)
        print("📊 [HCAT Observer] Menjalankan Validasi HCAT (4 Metrik)")
        print("=" * 60)

        # Siapkan query (apa yang ingin kita jawab)
        company_name = ai_report.get("company", {}).get("name", "Unknown")
        query_texts = [
            f"Siapa saja pemegang saham dan pengurus {company_name}?",
            f"Berapa struktur modal dan kepemilikan saham di {company_name}?",
            f"Apakah ada Ultimate Beneficial Owner (UBO) di {company_name}?",
            f"Bagaimana riwayat litigasi dan sengketa hukum {company_name}?",
            f"Apa klasifikasi risiko dan rekomendasi regulasi untuk {company_name}?",
            f"Apa saja kegiatan usaha (KBLI) {company_name}?"
        ]

        # Siapkan answer (jawaban AI dari report)
        risk = ai_report.get("risk_assessment", {})
        answer_texts = risk.get("key_findings", [])
        answer_texts.append(risk.get("regulatory_recommendation", ""))
        answer_texts.append(f"Risk Score: {risk.get('overall_risk_score', 0)}, Classification: {risk.get('risk_classification', 'Unknown')}")

        # Siapkan context sentences dari raw data
        context_sentences = []
        for raw_text in raw_data_texts:
            sentences = self._split_to_sentences(raw_text)
            context_sentences.extend(sentences)
        
        # Jika konteks terlalu sedikit, gunakan raw text langsung
        if len(context_sentences) < 3:
            context_sentences = raw_data_texts

        # Jalankan 4 metrik HCAT
        print("\n   📐 Menghitung Context Relevancy...")
        context_relevancy = self.calculate_context_relevancy(query_texts, context_sentences)
        print(f"      → Context Relevancy: {context_relevancy:.4f}")

        print("   📐 Menghitung Groundedness...")
        groundedness = self.calculate_groundedness(answer_texts, context_sentences)
        print(f"      → Groundedness: {groundedness:.4f}")

        print("   📐 Menghitung Completeness...")
        completeness = self.calculate_completeness(answer_texts, context_sentences)
        print(f"      → Completeness (Sentence Sim): {completeness['sentence_similarity']:.4f}")
        print(f"      → Completeness (Wasserstein):  {completeness['wasserstein']:.4f}")
        print(f"      → Completeness (Combined):     {completeness['combined']:.4f}")

        print("   📐 Menghitung Answer Relevancy...")
        answer_relevancy = self.calculate_answer_relevancy(answer_texts, query_texts)
        print(f"      → Answer Relevancy: {answer_relevancy:.4f}")

        # Assessment berdasarkan threshold
        thresholds = {
            "excellent": 0.85,
            "good": 0.75,
            "acceptable": 0.65,
            "poor": 0.0
        }

        def assess(score):
            if score >= thresholds["excellent"]:
                return "Excellent"
            elif score >= thresholds["good"]:
                return "Good"
            elif score >= thresholds["acceptable"]:
                return "Acceptable"
            else:
                return "Poor - Needs Improvement"

        result = {
            "company_target": company_name,
            "evaluation_framework": "HCAT (Human-Calibrated Automated Testing)",
            "metrics": {
                "context_relevancy": {
                    "score": round(context_relevancy, 4),
                    "assessment": assess(context_relevancy),
                    "description": "Seberapa relevan konteks sumber terhadap pertanyaan profiling"
                },
                "groundedness": {
                    "score": round(groundedness, 4),
                    "assessment": assess(groundedness),
                    "description": "Seberapa grounded jawaban AI pada data sumber (anti-halusinasi)"
                },
                "completeness": {
                    "sentence_similarity_score": completeness["sentence_similarity"],
                    "wasserstein_score": completeness["wasserstein"],
                    "combined_score": completeness["combined"],
                    "assessment": assess(completeness["combined"]),
                    "description": "Seberapa lengkap jawaban mencakup informasi dari konteks sumber"
                },
                "answer_relevancy": {
                    "score": round(answer_relevancy, 4),
                    "assessment": assess(answer_relevancy),
                    "description": "Seberapa relevan jawaban terhadap tujuan customer profiling"
                }
            },
            "overall_assessment": {
                "hallucination_risk": "High" if groundedness < 0.65 else ("Medium" if groundedness < 0.75 else "Low"),
                "data_coverage": "Comprehensive" if completeness["combined"] >= 0.75 else ("Partial" if completeness["combined"] >= 0.60 else "Insufficient"),
                "recommendation": "Model output reliable" if groundedness >= 0.75 and completeness["combined"] >= 0.65 else "Perlu review manual atau perbaikan prompt"
            }
        }

        # Simpan hasil ke file
        os.makedirs("validation_reports", exist_ok=True)
        file_path = f"validation_reports/hcat_eval_{company_name.replace(' ', '_')}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        print(f"\n   💾 HCAT Metrics tersimpan: {file_path}")

        # Summary
        print("\n   ╔══════════════════════════════════════════════╗")
        print("   ║          HCAT EVALUATION SUMMARY             ║")
        print("   ╠══════════════════════════════════════════════╣")
        print(f"   ║  Context Relevancy : {context_relevancy:.4f} ({assess(context_relevancy):>22s}) ║")
        print(f"   ║  Groundedness      : {groundedness:.4f} ({assess(groundedness):>22s}) ║")
        print(f"   ║  Completeness      : {completeness['combined']:.4f} ({assess(completeness['combined']):>22s}) ║")
        print(f"   ║  Answer Relevancy  : {answer_relevancy:.4f} ({assess(answer_relevancy):>22s}) ║")
        print("   ╠══════════════════════════════════════════════╣")
        hallucination = result["overall_assessment"]["hallucination_risk"]
        print(f"   ║  Hallucination Risk: {hallucination:>25s} ║")
        print(f"   ║  Data Coverage     : {result['overall_assessment']['data_coverage']:>25s} ║")
        print("   ╚══════════════════════════════════════════════╝")

        return result