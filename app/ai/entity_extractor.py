"""
Entity Extractor — LLM-powered entity and relationship extraction.

Processes document chunks to extract:
  - Entities: people, departments, processes, products, regulations, etc.
  - Relationships: between entities

Results are stored in Neo4j as:
  (:Entity {name, type, description})-[:MENTIONED_IN]->(:Document)
  (:Entity)-[:FOUND_IN {context}]->(:Chunk)
  (:Entity)-[:RELATES_TO {type}]->(:Entity)
"""

import json
import uuid
from typing import Optional

from loguru import logger

from app.services.neo4j_service import neo4j_service


# ---------------------------------------------------------------------------
# Entity types
# ---------------------------------------------------------------------------

ENTITY_TYPES = [
    "PERSON",       # Người, nhân vật
    "DEPARTMENT",   # Phòng ban, bộ phận
    "PROCESS",      # Quy trình, thủ tục
    "PRODUCT",      # Sản phẩm, dịch vụ
    "REGULATION",   # Quy định, chính sách
    "CONCEPT",      # Khái niệm, thuật ngữ
    "LOCATION",     # Địa điểm
    "ORGANIZATION", # Tổ chức bên ngoài
    "DATE_EVENT",   # Sự kiện có thời gian
]

EXTRACTION_PROMPT = """Bạn là trích xuất thực thể (entity extractor) chuyên nghiệp.

Từ đoạn văn bản dưới đây, trích xuất các thực thể (entities) và mối quan hệ (relationships).

LOẠI THỰC THỂ:
- PERSON: tên người, chức vụ cụ thể
- DEPARTMENT: phòng ban, bộ phận, đơn vị
- PROCESS: quy trình, thủ tục, workflow
- PRODUCT: sản phẩm, dịch vụ, hệ thống
- REGULATION: quy định, chính sách, điều luật
- CONCEPT: khái niệm, thuật ngữ quan trọng
- LOCATION: địa điểm, văn phòng
- ORGANIZATION: công ty, tổ chức bên ngoài
- DATE_EVENT: sự kiện có thời gian/deadline

QUY TẮC:
- CHỈ trích xuất thực thể THỰC SỰ QUAN TRỌNG, không lấy từ thông thường
- Tên thực thể phải CỤ THỂ (VD: "Phòng Nhân sự" chứ không phải "phòng ban")
- Mỗi thực thể có: name, type, description (1 dòng mô tả ngắn)
- Mối quan hệ: source → target với type mô tả quan hệ

Trả về JSON (KHÔNG có markdown code block):
{
  "entities": [
    {"name": "...", "type": "...", "description": "..."}
  ],
  "relationships": [
    {"source": "entity_name_1", "target": "entity_name_2", "type": "mô tả quan hệ"}
  ]
}

VĂN BẢN:
"""

# ---------------------------------------------------------------------------
# Batch size for extraction
# ---------------------------------------------------------------------------

BATCH_SIZE = 3  # chunks per Gemini call


async def extract_entities_from_chunks(
    chunks: list[dict],
    source_id: str,
    source_title: str,
) -> dict:
    """
    Extract entities and relationships from a list of chunks.
    
    Args:
        chunks: list of {"chunk_id": str, "content": str, "page_number": int}
        source_id: PG source ID
        source_title: Document title
        
    Returns:
        {"entities_count": int, "relationships_count": int}
    """
    if not neo4j_service.available:
        logger.debug("Neo4j not available, skipping entity extraction")
        return {"entities_count": 0, "relationships_count": 0}

    all_entities: dict[str, dict] = {}  # name -> entity
    all_relationships: list[dict] = []
    chunk_entity_map: dict[str, list[str]] = {}  # chunk_id -> [entity_names]

    # Process in batches
    for batch_start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[batch_start:batch_start + BATCH_SIZE]
        
        # Combine chunk content for batch extraction
        combined = ""
        for chunk in batch:
            combined += f"\n--- Đoạn (trang {chunk.get('page_number', '?')}) ---\n"
            combined += chunk["content"]
            combined += "\n"

        try:
            result = await _extract_batch(combined, session=None)  # session injected below
            
            # Collect entities
            for ent in result.get("entities", []):
                name = ent.get("name", "").strip()
                if not name or len(name) < 2:
                    continue
                if name not in all_entities:
                    all_entities[name] = {
                        "name": name,
                        "type": ent.get("type", "CONCEPT"),
                        "description": ent.get("description", ""),
                    }
                # Map entity to chunks in this batch
                for chunk in batch:
                    cid = chunk["chunk_id"]
                    if name.lower() in chunk["content"].lower():
                        chunk_entity_map.setdefault(cid, []).append(name)

            # Collect relationships
            for rel in result.get("relationships", []):
                src = rel.get("source", "").strip()
                tgt = rel.get("target", "").strip()
                rel_type = rel.get("type", "RELATES_TO")
                if src and tgt and src != tgt:
                    all_relationships.append({
                        "source": src,
                        "target": tgt,
                        "type": rel_type,
                    })

        except Exception as e:
            logger.warning(f"Entity extraction batch failed: {e}")
            continue

    # --- Persist to Neo4j ---
    if not all_entities:
        return {"entities_count": 0, "relationships_count": 0}

    entities_saved = 0
    rels_saved = 0

    async with neo4j_service._driver.session() as session:
        # Ensure document node exists
        await session.run(
            "MERGE (d:Document {pg_source_id: $sid}) SET d.title = $title",
            sid=source_id, title=source_title,
        )

        # Create entity nodes and MENTIONED_IN relationships
        for name, ent in all_entities.items():
            await session.run(
                """
                MERGE (e:Entity {name: $name})
                SET e.type = $type, e.description = $description
                WITH e
                MATCH (d:Document {pg_source_id: $sid})
                MERGE (e)-[:MENTIONED_IN]->(d)
                """,
                name=ent["name"],
                type=ent["type"],
                description=ent["description"],
                sid=source_id,
            )
            entities_saved += 1

        # Create chunk nodes and FOUND_IN relationships
        for chunk_id, entity_names in chunk_entity_map.items():
            # Ensure chunk node
            await session.run(
                """
                MERGE (ch:Chunk {pg_chunk_id: $cid})
                WITH ch
                MATCH (d:Document {pg_source_id: $sid})
                MERGE (ch)-[:PART_OF]->(d)
                """,
                cid=chunk_id, sid=source_id,
            )
            for ename in entity_names:
                await session.run(
                    """
                    MATCH (e:Entity {name: $ename})
                    MATCH (ch:Chunk {pg_chunk_id: $cid})
                    MERGE (e)-[:FOUND_IN]->(ch)
                    """,
                    ename=ename, cid=chunk_id,
                )

        # Create RELATES_TO relationships between entities
        for rel in all_relationships:
            if rel["source"] in all_entities and rel["target"] in all_entities:
                await session.run(
                    """
                    MATCH (a:Entity {name: $src})
                    MATCH (b:Entity {name: $tgt})
                    MERGE (a)-[r:RELATES_TO]->(b)
                    SET r.type = $type
                    """,
                    src=rel["source"],
                    tgt=rel["target"],
                    type=rel["type"],
                )
                rels_saved += 1

    logger.info(
        f"Entity extraction for '{source_title}': "
        f"{entities_saved} entities, {rels_saved} relationships"
    )
    return {"entities_count": entities_saved, "relationships_count": rels_saved}


async def _extract_batch(text: str, session=None) -> dict:
    """Call configured LLM provider to extract entities from a batch of text."""
    from app.database import async_session_factory
    from app.ai.registry import ProviderRegistry

    # If no session provided, create one
    if session is None:
        async with async_session_factory() as db:
            return await _extract_batch(text, session=db)

    registry = ProviderRegistry(session)
    try:
        llm = await registry.get_llm()
        result_text = await llm.generate(
            prompt=EXTRACTION_PROMPT + text,
            temperature=0.1,
            max_tokens=4096,
        )
    except Exception as e:
        logger.warning(f"Entity extraction LLM call failed: {e}")
        return {"entities": [], "relationships": []}

    result_text = result_text.strip()

    # Parse JSON
    if result_text.startswith("```"):
        lines = result_text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        result_text = "\n".join(lines).strip()

    try:
        return json.loads(result_text)
    except json.JSONDecodeError:
        start = result_text.find("{")
        end = result_text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(result_text[start:end])
            except json.JSONDecodeError:
                pass
        logger.warning(f"Failed to parse entity extraction JSON: {result_text[:200]}")
        return {"entities": [], "relationships": []}

