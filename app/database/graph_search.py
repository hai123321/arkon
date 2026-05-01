"""
Graph-enhanced search — leverages Neo4j entities for improved RAG.

Flow:
  1. Extract key terms/entities from user query
  2. Match against Neo4j Entity nodes (fuzzy name matching)
  3. Traverse 1-2 hops to find related entities
  4. Get pg_chunk_ids where these entities appear
  5. Return chunk IDs that can boost hybrid search results
"""

from typing import Optional

from loguru import logger

from app.services.neo4j_service import neo4j_service


async def graph_search(
    query: str,
    top_k: int = 10,
) -> list[dict]:
    """
    Find relevant chunks via entity traversal in Neo4j.
    
    Returns list of:
      {"pg_chunk_id": str, "entity_name": str, "entity_type": str, "path": str}
    """
    if not neo4j_service.available:
        return []

    try:
        async with neo4j_service._driver.session() as session:
            # Step 1: Find matching entities (case-insensitive contains)
            # Split query into words, match against entity names
            words = [w.strip() for w in query.split() if len(w.strip()) > 2]
            if not words:
                return []

            # Build regex pattern: match any word
            pattern = "|".join(words)

            result = await session.run(
                """
                MATCH (e:Entity)
                WHERE e.name =~ $pattern
                RETURN e.name AS name, e.type AS type
                LIMIT 10
                """,
                pattern=f"(?i).*({pattern}).*",
            )
            matched_entities = []
            async for record in result:
                matched_entities.append({
                    "name": record["name"],
                    "type": record["type"],
                })

            if not matched_entities:
                return []

            # Step 2: Get chunks where these entities appear (1-hop)
            entity_names = [e["name"] for e in matched_entities]
            result = await session.run(
                """
                UNWIND $names AS ename
                MATCH (e:Entity {name: ename})-[:FOUND_IN]->(ch:Chunk)
                RETURN DISTINCT ch.pg_chunk_id AS pg_chunk_id,
                       e.name AS entity_name,
                       e.type AS entity_type,
                       'direct' AS path
                LIMIT $limit
                """,
                names=entity_names,
                limit=top_k,
            )
            direct_chunks = []
            async for record in result:
                direct_chunks.append({
                    "pg_chunk_id": record["pg_chunk_id"],
                    "entity_name": record["entity_name"],
                    "entity_type": record["entity_type"],
                    "path": record["path"],
                })

            # Step 3: Also find chunks with RELATED entities (2-hop)
            remaining = top_k - len(direct_chunks)
            if remaining > 0:
                result = await session.run(
                    """
                    UNWIND $names AS ename
                    MATCH (e:Entity {name: ename})-[:RELATES_TO]-(related:Entity)-[:FOUND_IN]->(ch:Chunk)
                    WHERE NOT ch.pg_chunk_id IN $exclude
                    RETURN DISTINCT ch.pg_chunk_id AS pg_chunk_id,
                           related.name AS entity_name,
                           related.type AS entity_type,
                           'related_via_' + e.name AS path
                    LIMIT $limit
                    """,
                    names=entity_names,
                    exclude=[c["pg_chunk_id"] for c in direct_chunks],
                    limit=remaining,
                )
                async for record in result:
                    direct_chunks.append({
                        "pg_chunk_id": record["pg_chunk_id"],
                        "entity_name": record["entity_name"],
                        "entity_type": record["entity_type"],
                        "path": record["path"],
                    })

            logger.debug(
                f"Graph search: {len(matched_entities)} entities matched, "
                f"{len(direct_chunks)} chunks found"
            )
            return direct_chunks

    except Exception as e:
        logger.warning(f"Graph search failed: {e}")
        return []


def merge_with_graph_boost(
    hybrid_results: list,
    graph_chunk_ids: set[str],
    boost: float = 0.3,
) -> list:
    """
    Boost RRF scores for chunks found by both hybrid search and graph search.
    
    Args:
        hybrid_results: HybridSearchResult list from vector_search
        graph_chunk_ids: Set of pg_chunk_ids found by graph_search
        boost: Score boost multiplier for matching chunks
        
    Returns:
        Re-sorted hybrid_results with boosted scores
    """
    if not graph_chunk_ids:
        return hybrid_results

    for doc in hybrid_results:
        boosted = False
        for chunk in doc.chunks:
            if str(chunk.chunk_id) in graph_chunk_ids:
                chunk.score *= (1 + boost)
                boosted = True

        if boosted:
            # Recalculate document-level score
            doc.rrf_score = max(c.score for c in doc.chunks) if doc.chunks else doc.rrf_score

    # Re-sort by boosted scores
    hybrid_results.sort(key=lambda r: r.rrf_score, reverse=True)
    return hybrid_results
