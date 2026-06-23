from functools import lru_cache

from sentence_transformers import SentenceTransformer

from knowledge.family_kb.config import EMBED_MODEL


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    return SentenceTransformer(EMBED_MODEL)


def embed_texts(texts: list[str]) -> list[list[float]]:
    model = get_model()
    return model.encode(texts, normalize_embeddings=True).tolist()


def embed_query(query: str) -> list[float]:
    return embed_texts([query])[0]


def embedding_dimension() -> int:
    return get_model().get_sentence_embedding_dimension()


