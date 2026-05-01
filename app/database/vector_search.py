"""
pgvector + PostgreSQL full-text hybrid search with RRF scoring.

Supports three search modes:
  1. semantic_search()  — pure cosine similarity (original, kept as fallback)
  2. full_text_search() — PostgreSQL tsvector/tsquery
  3. hybrid_search()    — semantic + full-text combined with Reciprocal Rank Fusion
"""

import uuid
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select, text, func, literal_column
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import ChunkImage, Source, SourceChunk


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class SearchResult:
    """A single vector search result."""
    chunk_id: uuid.UUID
    source_id: uuid.UUID
    source_title: Optional[str]
    source_minio_key: Optional[str]  # MinIO key for original file download
    content: str
    similarity: float
    page_number: Optional[int]
    image_keys: list[str]  # MinIO keys for associated images


@dataclass
class HybridChunk:
    """A single chunk within a grouped document result."""
    chunk_id: uuid.UUID
    content: str
    page_number: Optional[int]
    score: float
    image_keys: list[str] = field(default_factory=list)


@dataclass
class HybridSearchResult:
    """Search result grouped by document (source), with ranked chunks."""
    document_id: uuid.UUID
    source_title: Optional[str]
    source_type: Optional[str]
    source_minio_key: Optional[str] = None  # MinIO key for original file
    rrf_score: float = 0.0
    chunks: list[HybridChunk] = field(default_factory=list)
    image_keys: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 1. Semantic search (original — kept as fallback)
# ---------------------------------------------------------------------------

async def semantic_search(
    session: AsyncSession,
    query_embedding: list[float],
    top_k: int = 10,
    min_similarity: float = 0.2,
) -> list[SearchResult]:
    """
    Cosine similarity search via pgvector.
    Returns top-K chunks with source metadata and associated images.
    """
    # pgvector cosine distance: 1 - (a <=> b)
    stmt = (
        select(
            SourceChunk.id,
            SourceChunk.source_id,
            SourceChunk.content,
            SourceChunk.page_number,
            Source.title.label("source_title"),
            Source.minio_key.label("source_minio_key"),
            (1 - SourceChunk.embedding.cosine_distance(query_embedding)).label(
                "similarity"
            ),
        )
        .join(Source, Source.id == SourceChunk.source_id)
        .where(Source.status == "ready")
        .order_by(SourceChunk.embedding.cosine_distance(query_embedding))
        .limit(top_k)
    )

    result = await session.execute(stmt)
    rows = result.all()

    results = []
    for row in rows:
        sim = float(row.similarity) if row.similarity else 0.0
        if sim < min_similarity:
            continue

        # Fetch associated images for this chunk
        img_stmt = select(ChunkImage.minio_key).where(
            ChunkImage.chunk_id == row.id
        )
        img_result = await session.execute(img_stmt)
        image_keys = [r[0] for r in img_result.all()]

        results.append(
            SearchResult(
                chunk_id=row.id,
                source_id=row.source_id,
                source_title=row.source_title,
                source_minio_key=row.source_minio_key,
                content=row.content,
                similarity=sim,
                page_number=row.page_number,
                image_keys=image_keys,
            )
        )

    return results


# ---------------------------------------------------------------------------
# 2. Full-text search (PostgreSQL tsvector)
# ---------------------------------------------------------------------------

async def full_text_search(
    session: AsyncSession,
    query_text: str,
    top_k: int = 10,
) -> list[SearchResult]:
    """
    PostgreSQL full-text search using tsvector/tsquery.
    Uses 'simple' config (no stemming) — works better for Vietnamese content.
    """
    if not query_text or not query_text.strip():
        return []

    # Build tsquery: split on spaces, join with '&' for AND matching
    # Also add prefix matching (:*) for partial word matches
    words = [w.strip() for w in query_text.split() if w.strip()]
    if not words:
        return []

    # Use plainto_tsquery for robustness (handles special chars)
    stmt = text("""
        SELECT 
            sc.id AS chunk_id,
            sc.source_id,
            sc.content,
            sc.page_number,
            s.title AS source_title,
            s.minio_key AS source_minio_key,
            ts_rank_cd(
                to_tsvector('simple', sc.content), 
                plainto_tsquery('simple', :query)
            ) AS rank
        FROM source_chunks sc
        JOIN sources s ON s.id = sc.source_id
        WHERE s.status = 'ready'
          AND to_tsvector('simple', sc.content) @@ plainto_tsquery('simple', :query)
        ORDER BY rank DESC
        LIMIT :top_k
    """)

    result = await session.execute(stmt, {"query": query_text, "top_k": top_k})
    rows = result.all()

    results = []
    for row in rows:
        # Fetch associated images
        img_stmt = select(ChunkImage.minio_key).where(
            ChunkImage.chunk_id == row.chunk_id
        )
        img_result = await session.execute(img_stmt)
        image_keys = [r[0] for r in img_result.all()]

        results.append(
            SearchResult(
                chunk_id=row.chunk_id,
                source_id=row.source_id,
                source_title=row.source_title,
                source_minio_key=row.source_minio_key,
                content=row.content,
                similarity=float(row.rank),
                page_number=row.page_number,
                image_keys=image_keys,
            )
        )

    return results


# ---------------------------------------------------------------------------
# 3. Hybrid search (Semantic + Full-text + RRF)
# ---------------------------------------------------------------------------

# RRF constant — standard value used in academic papers and SurfSense
RRF_K = 60


async def hybrid_search(
    session: AsyncSession,
    query_embedding: list[float],
    query_text: str,
    top_k: int = 10,
    semantic_weight: float = 1.0,
    keyword_weight: float = 1.0,
) -> list[HybridSearchResult]:
    """
    Hybrid search combining semantic (vector) and keyword (full-text) search
    using Reciprocal Rank Fusion (RRF).
    
    RRF Score = semantic_weight / (K + semantic_rank) + keyword_weight / (K + keyword_rank)
    
    Results are grouped by source document with their constituent chunks.
    
    Args:
        session: Database session
        query_embedding: Vector embedding of the query
        query_text: Raw text query for full-text search
        top_k: Number of final results to return
        semantic_weight: Weight multiplier for semantic search scores (default: 1.0)
        keyword_weight: Weight multiplier for keyword search scores (default: 1.0)
    
    Returns:
        List of HybridSearchResult grouped by document, sorted by RRF score
    """
    # Fetch more candidates than needed for RRF merging
    candidate_k = top_k * 3

    # --- Run both searches ---
    semantic_results = await semantic_search(
        session, query_embedding, top_k=candidate_k, min_similarity=0.1
    )

    keyword_results = await full_text_search(
        session, query_text, top_k=candidate_k
    )

    # --- Assign ranks ---
    semantic_ranked: dict[uuid.UUID, int] = {}
    for rank, r in enumerate(semantic_results, start=1):
        semantic_ranked[r.chunk_id] = rank

    keyword_ranked: dict[uuid.UUID, int] = {}
    for rank, r in enumerate(keyword_results, start=1):
        keyword_ranked[r.chunk_id] = rank

    # --- Compute RRF scores ---
    all_chunk_ids = set(semantic_ranked.keys()) | set(keyword_ranked.keys())

    chunk_scores: dict[uuid.UUID, float] = {}
    for cid in all_chunk_ids:
        score = 0.0
        if cid in semantic_ranked:
            score += semantic_weight / (RRF_K + semantic_ranked[cid])
        if cid in keyword_ranked:
            score += keyword_weight / (RRF_K + keyword_ranked[cid])
        chunk_scores[cid] = score

    # --- Build a lookup for chunk details ---
    chunk_details: dict[uuid.UUID, SearchResult] = {}
    for r in semantic_results:
        chunk_details[r.chunk_id] = r
    for r in keyword_results:
        if r.chunk_id not in chunk_details:
            chunk_details[r.chunk_id] = r

    # --- Group by document (source_id) ---
    doc_chunks: dict[uuid.UUID, list[tuple[float, SearchResult]]] = {}
    for cid, score in chunk_scores.items():
        detail = chunk_details.get(cid)
        if not detail:
            continue
        doc_id = detail.source_id
        if doc_id not in doc_chunks:
            doc_chunks[doc_id] = []
        doc_chunks[doc_id].append((score, detail))

    # --- Build results ---
    results: list[HybridSearchResult] = []
    for doc_id, chunks in doc_chunks.items():
        # Sort chunks by score within document
        chunks.sort(key=lambda x: x[0], reverse=True)

        # Document-level score = max chunk score (best representation)
        doc_score = chunks[0][0]

        # Get source metadata from first chunk
        first = chunks[0][1]
        
        # Collect all image keys
        all_image_keys = []
        for _, detail in chunks:
            all_image_keys.extend(detail.image_keys)

        hybrid_chunks = [
            HybridChunk(
                chunk_id=detail.chunk_id,
                content=detail.content,
                page_number=detail.page_number,
                score=score,
                image_keys=detail.image_keys,
            )
            for score, detail in chunks
        ]

        results.append(
            HybridSearchResult(
                document_id=doc_id,
                source_title=first.source_title,
                source_type=None,  # Will be enriched if needed
                source_minio_key=first.source_minio_key,
                rrf_score=doc_score,
                chunks=hybrid_chunks,
                image_keys=list(set(all_image_keys)),  # deduplicate
            )
        )

    # Sort by document-level RRF score
    results.sort(key=lambda r: r.rrf_score, reverse=True)

    return results[:top_k]
