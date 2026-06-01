"""
HCAT Evaluator — Human-Calibrated Automated Testing
=====================================================
Phase 5 dari KYB Pipeline:
Evaluasi draf narasi JSON dari Fusion Agent sebelum dicetak ke PDF.

Metrik HCAT (sesuai paper):
1. Context Relevancy  — seberapa relevan konteks sumber terhadap query
2. Groundedness       — seberapa grounded jawaban AI pada konteks sumber
3. Completeness       — seberapa lengkap jawaban AI mencakup informasi konteks
4. Answer Relevancy   — seberapa relevan jawaban terhadap pertanyaan/tujuan

Menggunakan sentence-level embedding comparison dengan cosine similarity
dan Wasserstein Distance untuk completeness.
"""

import json
import os
import re
import time

import numpy as np
from google import genai

from src.config import GEMINI_API_KEY

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
client = genai.Client(api_key=GEMINI_API_KEY)


class HCATEvaluator:
    """
    Human-Calibrated Automated Testing (HCAT) Framework.
    
    Moved from src/validation/hcat_tester.py → src/agents/hcat_evaluator.py
    as specified in the KYB Python Implementation Framework.
    """

    def __init__(self):
        self.client = client
        self.embedding_model = EMBEDDING_MODEL

    def _get_embedding(self, text: str) -> list:
        """Dapatkan embedding vektor dari teks menggunakan Gemini Embedding Model."""
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
                    time.sleep(2)
                else:
                    return []

    def _get_embeddings_batch(self, texts: list) -> list:
        """Dapatkan embeddings untuk banyak teks sekaligus."""
        embeddings = []
        for text in texts:
            emb = self._get_embedding(text)
            if emb:
                embeddings.append(emb)
            time.sleep(0.1)
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
        sentences = re.split(r'[.!?\n]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        return sentences

    # ── METRIK 1: CONTEXT RELEVANCY ──────────────────────────────────────────

    def calculate_context_relevancy(self, query_sentences: list,
                                    context_sentences: list) -> float:
        """
        S_max(q_i) = max_{1≤j≤n} Sim(q_i, c_j)
        S_c-relevancy = (1/m) * Σ S_max(q_i)
        """
        if not query_sentences or not context_sentences:
            return 0.0

        q_embeddings = self._get_embeddings_batch(query_sentences)
        c_embeddings = self._get_embeddings_batch(context_sentences)

        if not q_embeddings or not c_embeddings:
            return 0.0

        max_sims = []
        for q_vec in q_embeddings:
            sims = [self._cosine_similarity(q_vec, c_vec) for c_vec in c_embeddings]
            max_sims.append(max(sims) if sims else 0.0)

        return float(np.mean(max_sims))

    # ── METRIK 2: GROUNDEDNESS ───────────────────────────────────────────────

    def calculate_groundedness(self, answer_sentences: list,
                               context_sentences: list) -> float:
        """
        S_max(a_i) = max_{1≤j≤n} Sim(a_i, c_j)
        S_groundedness = (1/k) * Σ S_max(a_i)
        """
        if not answer_sentences or not context_sentences:
            return 0.0

        a_embeddings = self._get_embeddings_batch(answer_sentences)
        c_embeddings = self._get_embeddings_batch(context_sentences)

        if not a_embeddings or not c_embeddings:
            return 0.0

        max_sims = []
        for a_vec in a_embeddings:
            sims = [self._cosine_similarity(a_vec, c_vec) for c_vec in c_embeddings]
            max_sims.append(max(sims) if sims else 0.0)

        return float(np.mean(max_sims))

    # ── METRIK 3: COMPLETENESS ───────────────────────────────────────────────

    def calculate_completeness(self, answer_sentences: list,
                               context_sentences: list) -> dict:
        """
        A) Sentence Similarity:
           S_max(c_i) = max_{1≤j≤k} Sim(c_i, a_j)
           S_completeness = (1/n) * Σ S_max(c_i)

        B) Wasserstein Distance:
           W(C, A) = (1/nk) * Σ_i Σ_j d(c_i, a_j)
           Completeness_W = 1 - W(C, A)
        """
        if not answer_sentences or not context_sentences:
            return {"sentence_similarity": 0.0, "wasserstein": 0.0, "combined": 0.0}

        c_embeddings = self._get_embeddings_batch(context_sentences)
        a_embeddings = self._get_embeddings_batch(answer_sentences)

        if not c_embeddings or not a_embeddings:
            return {"sentence_similarity": 0.0, "wasserstein": 0.0, "combined": 0.0}

        # A) Sentence Similarity
        max_sims = []
        for c_vec in c_embeddings:
            sims = [self._cosine_similarity(c_vec, a_vec) for a_vec in a_embeddings]
            max_sims.append(max(sims) if sims else 0.0)
        ss_score = float(np.mean(max_sims))

        # B) Wasserstein Distance
        n = len(c_embeddings)
        k = len(a_embeddings)
        total_cost = sum(
            1.0 - self._cosine_similarity(c_vec, a_vec)
            for c_vec in c_embeddings
            for a_vec in a_embeddings
        )
        w_dist = total_cost / (n * k)
        w_score = float(1.0 - w_dist)

        combined = float((ss_score + w_score) / 2)

        return {
            "sentence_similarity": round(ss_score, 4),
            "wasserstein": round(w_score, 4),
            "combined": round(combined, 4),
        }

    # ── METRIK 4: ANSWER RELEVANCY ───────────────────────────────────────────

    def calculate_answer_relevancy(self, answer_sentences: list,
                                   query_sentences: list) -> float:
        """
        S_max(a_i) = max_{1≤j≤m} Sim(a_i, q_j)
        S_a-relevancy = (1/k) * Σ S_max(a_i)
        """
        if not answer_sentences or not query_sentences:
            return 0.0

        a_embeddings = self._get_embeddings_batch(answer_sentences)
        q_embeddings = self._get_embeddings_batch(query_sentences)

        if not a_embeddings or not q_embeddings:
            return 0.0

        max_sims = []
        for a_vec in a_embeddings:
            sims = [self._cosine_similarity(a_vec, q_vec) for q_vec in q_embeddings]
            max_sims.append(max(sims) if sims else 0.0)

        return float(np.mean(max_sims))

    # ── MAIN EVALUATION ─────────────────────────────────────────────────────

    def run_evaluation(self, raw_data_texts: list,
                       kyb_output_dict: dict) -> dict:
        """
        Jalankan evaluasi HCAT lengkap (4 metrik).

        Args:
            raw_data_texts: List teks data mentah (dari 4 sumber)
            kyb_output_dict: Dict KYBInvestigationOutput

        Returns:
            Dict berisi semua metrik HCAT + confidence
        """
        print("\n" + "=" * 62)
        print("📊  PHASE 5: HCAT EVALUATION (Validation)")
        print("=" * 62)

        company_name = kyb_output_dict.get("corporate_entity", {}).get("name", "Unknown")

        # Query texts
        query_texts = [
            f"Siapa saja pemegang saham dan pengurus {company_name}?",
            f"Berapa struktur modal dan kepemilikan saham di {company_name}?",
            f"Apakah ada Ultimate Beneficial Owner (UBO) di {company_name}?",
            f"Bagaimana riwayat litigasi dan sengketa hukum {company_name}?",
            f"Apa klasifikasi risiko dan rekomendasi regulasi untuk {company_name}?",
            f"Apa saja kegiatan usaha (KBLI) {company_name}?",
        ]

        # Answer texts (dari intelligence findings + recommendation)
        answer_texts = []
        for dim in kyb_output_dict.get("intelligence_data", []):
            if dim.get("finding"):
                answer_texts.append(dim["finding"])
        reco = kyb_output_dict.get("ai_recommendation", {})
        if reco.get("narrative"):
            answer_texts.append(reco["narrative"])
        score = kyb_output_dict.get("ai_risk_scoring", {})
        answer_texts.append(
            f"Risk Score: {score.get('risk_contamination_score', 0)}, "
            f"Level: {score.get('overall_risk_level', '?')}"
        )

        # Context sentences dari raw data
        context_sentences = []
        for raw_text in raw_data_texts:
            context_sentences.extend(self._split_to_sentences(raw_text))
        if len(context_sentences) < 3:
            context_sentences = raw_data_texts

        # Run 4 metrics
        print("\n   📐 Menghitung Context Relevancy...")
        ctx_rel = self.calculate_context_relevancy(query_texts, context_sentences)
        print(f"      → {ctx_rel:.4f}")

        print("   📐 Menghitung Groundedness...")
        grnd = self.calculate_groundedness(answer_texts, context_sentences)
        print(f"      → {grnd:.4f}")

        print("   📐 Menghitung Completeness...")
        comp = self.calculate_completeness(answer_texts, context_sentences)
        print(f"      → Combined: {comp['combined']:.4f}")

        print("   📐 Menghitung Answer Relevancy...")
        ans_rel = self.calculate_answer_relevancy(answer_texts, query_texts)
        print(f"      → {ans_rel:.4f}")

        # Assess
        def assess(s):
            if s >= 0.85:
                return "Excellent"
            elif s >= 0.75:
                return "Good"
            elif s >= 0.65:
                return "Acceptable"
            return "Poor - Needs Improvement"

        # HCAT confidence score (disematkan di PDF)
        confidence = round((ctx_rel + grnd + comp["combined"] + ans_rel) / 4 * 100, 1)

        result = {
            "company_target": company_name,
            "hcat_confidence_pct": confidence,
            "metrics": {
                "context_relevancy": {"score": round(ctx_rel, 4), "assessment": assess(ctx_rel)},
                "groundedness": {"score": round(grnd, 4), "assessment": assess(grnd)},
                "completeness": {
                    "sentence_similarity": comp["sentence_similarity"],
                    "wasserstein": comp["wasserstein"],
                    "combined": comp["combined"],
                    "assessment": assess(comp["combined"]),
                },
                "answer_relevancy": {"score": round(ans_rel, 4), "assessment": assess(ans_rel)},
            },
            "overall_assessment": {
                "hallucination_risk": "High" if grnd < 0.65 else ("Medium" if grnd < 0.75 else "Low"),
                "data_coverage": (
                    "Comprehensive" if comp["combined"] >= 0.75
                    else ("Partial" if comp["combined"] >= 0.60 else "Insufficient")
                ),
                "recommendation": (
                    "Model output reliable"
                    if grnd >= 0.75 and comp["combined"] >= 0.65
                    else "Perlu review manual"
                ),
            },
        }

        # Save
        os.makedirs("validation_reports", exist_ok=True)
        safe = company_name.replace(" ", "_")
        fpath = f"validation_reports/hcat_eval_{safe}.json"
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        # Summary
        print(f"\n   ╔══════════════════════════════════════════════╗")
        print(f"   ║          HCAT EVALUATION SUMMARY             ║")
        print(f"   ╠══════════════════════════════════════════════╣")
        print(f"   ║  Context Relevancy : {ctx_rel:.4f} ({assess(ctx_rel):>22s}) ║")
        print(f"   ║  Groundedness      : {grnd:.4f} ({assess(grnd):>22s}) ║")
        print(f"   ║  Completeness      : {comp['combined']:.4f} ({assess(comp['combined']):>22s}) ║")
        print(f"   ║  Answer Relevancy  : {ans_rel:.4f} ({assess(ans_rel):>22s}) ║")
        print(f"   ╠══════════════════════════════════════════════╣")
        print(f"   ║  HCAT Confidence   : {confidence:>25.1f}% ║")
        print(f"   ╚══════════════════════════════════════════════╝")
        print(f"   💾 Disimpan: {fpath}")

        return result
