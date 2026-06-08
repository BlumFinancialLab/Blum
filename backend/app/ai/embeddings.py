from __future__ import annotations

from functools import cached_property
import hashlib
import math
import numpy as np

from app.core.config import get_settings


class EmbeddingModel:
    def __init__(self):
        self.settings = get_settings()
        self.model_name = self.settings.embedding_model

    @cached_property
    def model(self):
        if not self.settings.enable_model_loading:
            return None
        try:
            from sentence_transformers import SentenceTransformer

            return SentenceTransformer(self.settings.embedding_model)
        except Exception:
            return None

    def embed_text(self, text: str) -> list[float]:
        text = (text or "").strip()
        if not text:
            return []
        if self.model is not None:
            try:
                vector = self.model.encode([text], normalize_embeddings=True)[0]
                return [round(float(x), 6) for x in vector.tolist()]
            except Exception:
                pass
        return deterministic_embedding(text)

    def similarity(self, query: str, vectors: list[list[float]]) -> list[float]:
        query_vector = np.array(self.embed_text(query), dtype=float)
        if query_vector.size == 0:
            return [0.0 for _ in vectors]
        faiss_scores = faiss_similarity(query_vector, vectors)
        if faiss_scores is not None:
            return faiss_scores
        scores = []
        for vector in vectors:
            candidate = np.array(vector, dtype=float)
            if candidate.size != query_vector.size:
                scores.append(0.0)
                continue
            denom = np.linalg.norm(query_vector) * np.linalg.norm(candidate)
            scores.append(float(np.dot(query_vector, candidate) / denom) if denom else 0.0)
        return scores


def deterministic_embedding(text: str, dims: int = 384) -> list[float]:
    """Small deterministic fallback used only when sentence-transformers cannot load."""
    vector = np.zeros(dims, dtype=float)
    for token in text.lower().split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dims
        sign = 1 if digest[4] % 2 == 0 else -1
        vector[idx] += sign
    norm = math.sqrt(float(np.dot(vector, vector)))
    if norm:
        vector = vector / norm
    return [round(float(x), 6) for x in vector.tolist()]


def faiss_similarity(query_vector: np.ndarray, vectors: list[list[float]]) -> list[float] | None:
    try:
        import faiss

        matrix = np.array(vectors, dtype="float32")
        if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] != query_vector.size:
            return None
        faiss.normalize_L2(matrix)
        query = query_vector.astype("float32").reshape(1, -1)
        faiss.normalize_L2(query)
        index = faiss.IndexFlatIP(matrix.shape[1])
        index.add(matrix)
        scores, indexes = index.search(query, matrix.shape[0])
        ranked = [0.0 for _ in vectors]
        for idx, score in zip(indexes[0], scores[0]):
            ranked[int(idx)] = float(score)
        return ranked
    except Exception:
        return None
