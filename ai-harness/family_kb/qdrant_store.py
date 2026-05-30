from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from family_kb.config import COLLECTION, QDRANT_URL
from family_kb.embeddings import embedding_dimension


def get_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL)


def ensure_collection() -> None:
    client = get_client()
    names = [c.name for c in client.get_collections().collections]

    if COLLECTION not in names:
        client.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(
                size=embedding_dimension(),
                distance=Distance.COSINE,
            ),
        )


def upsert_points(points: list[PointStruct]) -> None:
    if not points:
        return

    ensure_collection()
    get_client().upsert(collection_name=COLLECTION, points=points)



def search_points(
    query_vector: list[float],
    limit: int,
    category: str | None = None,
):
    ensure_collection()

    q_filter = None

    if category:
        q_filter = Filter(
            must=[
                FieldCondition(
                    key="category",
                    match=MatchValue(value=category),
                )
            ]
        )

    response = get_client().query_points(
        collection_name=COLLECTION,
        query=query_vector,
        query_filter=q_filter,
        limit=limit,
    )

    return response.points


