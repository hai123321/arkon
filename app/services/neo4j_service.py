"""
Neo4j Knowledge Graph service — manages categories, document-category links,
and contact-category links for the GraphRAG pipeline.

Node types:
  (:Category {id, name, description, parent_id, sort_order})
  (:Document {id, pg_source_id, title})
  (:Contact  {id, pg_contact_id, name, role})

Relationships:
  (child:Category)-[:CHILD_OF]->(parent:Category)
  (doc:Document)-[:BELONGS_TO]->(cat:Category)
  (contact:Contact)-[:RESPONSIBLE_FOR]->(cat:Category)
"""

import uuid
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger
from neo4j import AsyncGraphDatabase, AsyncDriver

from app.config import settings


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CategoryNode:
    id: str
    name: str
    description: Optional[str] = None
    parent_id: Optional[str] = None
    sort_order: int = 0
    source_count: int = 0
    contact_count: int = 0
    children: list["CategoryNode"] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Service singleton
# ---------------------------------------------------------------------------

class Neo4jService:
    """Async Neo4j service for category and knowledge graph operations."""

    _driver: Optional[AsyncDriver] = None

    async def connect(self) -> None:
        """Initialize the Neo4j async driver and create constraints."""
        if self._driver:
            return
        try:
            self._driver = AsyncGraphDatabase.driver(
                settings.neo4j_uri,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            # Verify connectivity
            await self._driver.verify_connectivity()
            logger.success(f"Neo4j connected: {settings.neo4j_uri}")

            # Create constraints & indexes
            await self._ensure_schema()
        except Exception as e:
            logger.warning(f"Neo4j connection failed: {e}")
            self._driver = None

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("Neo4j connection closed")

    @property
    def available(self) -> bool:
        return self._driver is not None

    async def _ensure_schema(self) -> None:
        """Create uniqueness constraints and indexes."""
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Category) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document) REQUIRE d.pg_source_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (ct:Contact) REQUIRE ct.pg_contact_id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (ch:Chunk) REQUIRE ch.pg_chunk_id IS UNIQUE",
        ]
        async with self._driver.session() as session:
            for cypher in constraints:
                await session.run(cypher)
        logger.info("Neo4j schema constraints ensured")

    # -----------------------------------------------------------------------
    # Category CRUD
    # -----------------------------------------------------------------------

    async def create_category(
        self,
        name: str,
        description: Optional[str] = None,
        parent_id: Optional[str] = None,
        sort_order: int = 0,
    ) -> CategoryNode:
        cat_id = str(uuid.uuid4())
        async with self._driver.session() as session:
            await session.run(
                """
                CREATE (c:Category {
                    id: $id, name: $name, description: $description,
                    parent_id: $parent_id, sort_order: $sort_order
                })
                """,
                id=cat_id, name=name, description=description,
                parent_id=parent_id, sort_order=sort_order,
            )
            # Create CHILD_OF relationship if parent exists
            if parent_id:
                await session.run(
                    """
                    MATCH (child:Category {id: $child_id})
                    MATCH (parent:Category {id: $parent_id})
                    MERGE (child)-[:CHILD_OF]->(parent)
                    """,
                    child_id=cat_id, parent_id=parent_id,
                )
        return CategoryNode(
            id=cat_id, name=name, description=description,
            parent_id=parent_id, sort_order=sort_order,
        )

    async def update_category(
        self,
        category_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        parent_id: Optional[str] = "__unchanged__",
        sort_order: Optional[int] = None,
    ) -> Optional[CategoryNode]:
        sets = []
        params: dict = {"id": category_id}

        if name is not None:
            sets.append("c.name = $name")
            params["name"] = name
        if description is not None:
            sets.append("c.description = $description")
            params["description"] = description
        if sort_order is not None:
            sets.append("c.sort_order = $sort_order")
            params["sort_order"] = sort_order

        async with self._driver.session() as session:
            if sets:
                cypher = f"MATCH (c:Category {{id: $id}}) SET {', '.join(sets)} RETURN c"
                result = await session.run(cypher, **params)
                record = await result.single()
                if not record:
                    return None

            # Handle parent change
            if parent_id != "__unchanged__":
                # Remove old parent relationship
                await session.run(
                    "MATCH (c:Category {id: $id})-[r:CHILD_OF]->() DELETE r",
                    id=category_id,
                )
                if parent_id:
                    await session.run(
                        """
                        MATCH (child:Category {id: $child_id})
                        MATCH (parent:Category {id: $parent_id})
                        MERGE (child)-[:CHILD_OF]->(parent)
                        """,
                        child_id=category_id, parent_id=parent_id,
                    )
                # Update the stored parent_id
                await session.run(
                    "MATCH (c:Category {id: $id}) SET c.parent_id = $parent_id",
                    id=category_id, parent_id=parent_id,
                )

            # Re-fetch
            result = await session.run(
                "MATCH (c:Category {id: $id}) RETURN c", id=category_id,
            )
            record = await result.single()
            if not record:
                return None
            node = record["c"]
            return CategoryNode(
                id=node["id"], name=node["name"],
                description=node.get("description"),
                parent_id=node.get("parent_id"),
                sort_order=node.get("sort_order", 0),
            )

    async def delete_category(self, category_id: str) -> bool:
        async with self._driver.session() as session:
            # Detach delete (removes all relationships too)
            result = await session.run(
                "MATCH (c:Category {id: $id}) DETACH DELETE c RETURN count(c) as cnt",
                id=category_id,
            )
            record = await result.single()
            return record and record["cnt"] > 0

    async def get_categories_flat(self) -> list[CategoryNode]:
        """Get all categories as a flat list with source/contact counts."""
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (c:Category)
                OPTIONAL MATCH (d:Document)-[:BELONGS_TO]->(c)
                OPTIONAL MATCH (ct:Contact)-[:RESPONSIBLE_FOR]->(c)
                RETURN c,
                       count(DISTINCT d) as source_count,
                       count(DISTINCT ct) as contact_count
                ORDER BY c.sort_order, c.name
                """
            )
            categories = []
            async for record in result:
                node = record["c"]
                categories.append(CategoryNode(
                    id=node["id"],
                    name=node["name"],
                    description=node.get("description"),
                    parent_id=node.get("parent_id"),
                    sort_order=node.get("sort_order", 0),
                    source_count=record["source_count"],
                    contact_count=record["contact_count"],
                ))
            return categories

    async def get_category_tree(self) -> list[CategoryNode]:
        """Get categories organized as a tree (roots with nested children)."""
        flat = await self.get_categories_flat()
        by_id = {c.id: c for c in flat}
        roots: list[CategoryNode] = []
        for cat in flat:
            if cat.parent_id and cat.parent_id in by_id:
                by_id[cat.parent_id].children.append(cat)
            else:
                roots.append(cat)
        return roots

    # -----------------------------------------------------------------------
    # Document ↔ Category links
    # -----------------------------------------------------------------------

    async def ensure_document(self, pg_source_id: str, title: str) -> None:
        """Create or update a Document node linked to a PG source."""
        async with self._driver.session() as session:
            await session.run(
                """
                MERGE (d:Document {pg_source_id: $pg_source_id})
                SET d.title = $title
                """,
                pg_source_id=pg_source_id, title=title,
            )

    async def link_source_to_categories(
        self, pg_source_id: str, category_ids: list[str],
    ) -> None:
        """Replace all BELONGS_TO relationships for a document."""
        async with self._driver.session() as session:
            # Remove existing
            await session.run(
                "MATCH (d:Document {pg_source_id: $sid})-[r:BELONGS_TO]->() DELETE r",
                sid=pg_source_id,
            )
            # Create new links
            if category_ids:
                await session.run(
                    """
                    MATCH (d:Document {pg_source_id: $sid})
                    UNWIND $cat_ids AS cid
                    MATCH (c:Category {id: cid})
                    MERGE (d)-[:BELONGS_TO]->(c)
                    """,
                    sid=pg_source_id, cat_ids=category_ids,
                )

    async def get_source_categories(self, pg_source_id: str) -> list[CategoryNode]:
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (d:Document {pg_source_id: $sid})-[:BELONGS_TO]->(c:Category)
                RETURN c ORDER BY c.sort_order, c.name
                """,
                sid=pg_source_id,
            )
            return [
                CategoryNode(
                    id=record["c"]["id"],
                    name=record["c"]["name"],
                    description=record["c"].get("description"),
                    parent_id=record["c"].get("parent_id"),
                    sort_order=record["c"].get("sort_order", 0),
                )
                async for record in result
            ]

    async def delete_document(self, pg_source_id: str) -> None:
        """Remove document node and all its relationships, plus orphaned chunks and entities."""
        async with self._driver.session() as session:
            # 1. Delete associated chunks
            await session.run(
                "MATCH (ch:Chunk)-[:PART_OF]->(d:Document {pg_source_id: $sid}) DETACH DELETE ch",
                sid=pg_source_id,
            )
            # 2. Delete the document node itself
            await session.run(
                "MATCH (d:Document {pg_source_id: $sid}) DETACH DELETE d",
                sid=pg_source_id,
            )
            # 3. Clean up orphaned entities (entities that have no MENTIONED_IN left)
            await session.run(
                "MATCH (e:Entity) WHERE NOT (e)-[:MENTIONED_IN]->() DETACH DELETE e"
            )

    # -----------------------------------------------------------------------
    # Contact ↔ Category links
    # -----------------------------------------------------------------------

    async def ensure_contact(self, pg_contact_id: str, name: str, role: Optional[str] = None) -> None:
        async with self._driver.session() as session:
            await session.run(
                """
                MERGE (ct:Contact {pg_contact_id: $pid})
                SET ct.name = $name, ct.role = $role
                """,
                pid=pg_contact_id, name=name, role=role,
            )

    async def link_contact_to_categories(
        self, pg_contact_id: str, category_ids: list[str],
    ) -> None:
        """Replace all RESPONSIBLE_FOR relationships for a contact."""
        async with self._driver.session() as session:
            await session.run(
                "MATCH (ct:Contact {pg_contact_id: $pid})-[r:RESPONSIBLE_FOR]->() DELETE r",
                pid=pg_contact_id,
            )
            if category_ids:
                await session.run(
                    """
                    MATCH (ct:Contact {pg_contact_id: $pid})
                    UNWIND $cat_ids AS cid
                    MATCH (c:Category {id: cid})
                    MERGE (ct)-[:RESPONSIBLE_FOR]->(c)
                    """,
                    pid=pg_contact_id, cat_ids=category_ids,
                )

    async def get_contact_categories(self, pg_contact_id: str) -> list[CategoryNode]:
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (ct:Contact {pg_contact_id: $pid})-[:RESPONSIBLE_FOR]->(c:Category)
                RETURN c ORDER BY c.sort_order, c.name
                """,
                pid=pg_contact_id,
            )
            return [
                CategoryNode(
                    id=record["c"]["id"],
                    name=record["c"]["name"],
                    description=record["c"].get("description"),
                    parent_id=record["c"].get("parent_id"),
                    sort_order=record["c"].get("sort_order", 0),
                )
                async for record in result
            ]

    async def get_contacts_for_categories(self, category_ids: list[str]) -> list[dict]:
        """Find contacts responsible for given categories (for agent suggestions)."""
        async with self._driver.session() as session:
            result = await session.run(
                """
                UNWIND $cat_ids AS cid
                MATCH (ct:Contact)-[:RESPONSIBLE_FOR]->(c:Category {id: cid})
                RETURN DISTINCT ct.pg_contact_id AS contact_id,
                       ct.name AS name, ct.role AS role,
                       collect(DISTINCT c.name) AS categories
                """,
                cat_ids=category_ids,
            )
            contacts = []
            async for record in result:
                contacts.append({
                    "contact_id": record["contact_id"],
                    "name": record["name"],
                    "role": record["role"],
                    "categories": record["categories"],
                })
            return contacts

    async def delete_contact(self, pg_contact_id: str) -> None:
        async with self._driver.session() as session:
            await session.run(
                "MATCH (ct:Contact {pg_contact_id: $pid}) DETACH DELETE ct",
                pid=pg_contact_id,
            )

    # -----------------------------------------------------------------------
    # Graph visualization
    # -----------------------------------------------------------------------

    async def get_graph_overview(self, limit: int = 300) -> dict:
        """
        Get nodes and edges for graph visualization.
        Only returns Arkon-specific nodes (not other projects sharing Neo4j).
        Returns: {"nodes": [...], "edges": [...], "stats": {...}}
        """
        nodes: list[dict] = []
        edges: list[dict] = []
        node_ids: set[str] = set()

        async with self._driver.session() as session:
            # Get Arkon nodes only:
            # - Entity: has 'type' property (PERSON, DEPARTMENT, etc.)
            # - Document: has 'pg_source_id' property
            # - Category: has our 'id' (UUID) and 'sort_order'
            # - Contact: has 'pg_contact_id' property
            result = await session.run(
                """
                MATCH (n)
                WHERE (n:Entity AND n.type IS NOT NULL AND n.type IN ['PERSON','DEPARTMENT','PROCESS','PRODUCT','REGULATION','CONCEPT','LOCATION','ORGANIZATION','DATE_EVENT'])
                   OR (n:Document AND n.pg_source_id IS NOT NULL)
                   OR (n:Category AND n.sort_order IS NOT NULL)
                   OR (n:Contact AND n.pg_contact_id IS NOT NULL)
                RETURN 
                    elementId(n) AS id,
                    labels(n) AS labels,
                    properties(n) AS props
                LIMIT $limit
                """,
                limit=limit,
            )
            async for record in result:
                nid = record["id"]
                labels = record["labels"]
                props = dict(record["props"])
                label = labels[0] if labels else "Unknown"

                name = (
                    props.get("name")
                    or props.get("title")
                    or props.get("id", "")[:12]
                )

                nodes.append({
                    "id": nid,
                    "label": label,
                    "name": name,
                    "type": props.get("type", ""),
                    "description": props.get("description", ""),
                })
                node_ids.add(nid)

            # Get relationships only between our nodes
            result = await session.run(
                """
                MATCH (a)-[r]->(b)
                WHERE ((a:Entity AND a.type IS NOT NULL) OR (a:Document AND a.pg_source_id IS NOT NULL)
                       OR (a:Category AND a.sort_order IS NOT NULL) OR (a:Contact AND a.pg_contact_id IS NOT NULL))
                  AND ((b:Entity AND b.type IS NOT NULL) OR (b:Document AND b.pg_source_id IS NOT NULL)
                       OR (b:Category AND b.sort_order IS NOT NULL) OR (b:Contact AND b.pg_contact_id IS NOT NULL))
                RETURN 
                    elementId(a) AS source,
                    elementId(b) AS target,
                    type(r) AS rel_type,
                    properties(r) AS props
                LIMIT $limit
                """,
                limit=limit * 3,
            )
            async for record in result:
                src = record["source"]
                tgt = record["target"]
                if src in node_ids and tgt in node_ids:
                    edges.append({
                        "source": src,
                        "target": tgt,
                        "type": record["rel_type"],
                        "label": record["props"].get("type", record["rel_type"]),
                    })

            # Stats — only our labels
            stats = {
                "Entity": len([n for n in nodes if n["label"] == "Entity"]),
                "Document": len([n for n in nodes if n["label"] == "Document"]),
                "Category": len([n for n in nodes if n["label"] == "Category"]),
                "Contact": len([n for n in nodes if n["label"] == "Contact"]),
            }
            # Remove zero counts
            stats = {k: v for k, v in stats.items() if v > 0}

        return {
            "nodes": nodes,
            "edges": edges,
            "stats": stats,
        }


# Singleton instance
neo4j_service = Neo4jService()
