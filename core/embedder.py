"""Embedding wrapper — single source of truth for vector creation."""
from __future__ import annotations

from sentence_transformers import SentenceTransformer

_models: dict[str, SentenceTransformer] = {}


def get_model(model_name: str = "nomic-ai/nomic-embed-text-v1") -> SentenceTransformer:
    if model_name not in _models:
        _models[model_name] = SentenceTransformer(model_name, trust_remote_code=True)
    return _models[model_name]


def embed(texts: list[str], model_name: str = "nomic-ai/nomic-embed-text-v1",
          batch_size: int = 64) -> list[list[float]]:
    if not texts:
        return []
    model = get_model(model_name)
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return vectors.tolist()


def embed_query(text: str, model_name: str = "nomic-ai/nomic-embed-text-v1") -> list[float]:
    prefixed = f"search_query: {text}"
    return embed([prefixed], model_name=model_name)[0]
