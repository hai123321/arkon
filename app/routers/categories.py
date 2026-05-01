"""
Categories router — CRUD for knowledge graph categories (Neo4j).

Categories are shared between Sources (BELONGS_TO) and Contacts (RESPONSIBLE_FOR).
"""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.neo4j_service import neo4j_service, CategoryNode

router = APIRouter()


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    parent_id: Optional[str] = None
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    parent_id: Optional[str] = "__unchanged__"
    sort_order: Optional[int] = None


class CategoryResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    parent_id: Optional[str] = None
    sort_order: int = 0
    source_count: int = 0
    contact_count: int = 0
    children: list["CategoryResponse"] = []


class LinkCategoriesRequest(BaseModel):
    category_ids: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_neo4j():
    if not neo4j_service.available:
        raise HTTPException(503, "Neo4j Knowledge Graph is not connected")


def _to_response(node: CategoryNode) -> CategoryResponse:
    return CategoryResponse(
        id=node.id,
        name=node.name,
        description=node.description,
        parent_id=node.parent_id,
        sort_order=node.sort_order,
        source_count=node.source_count,
        contact_count=node.contact_count,
        children=[_to_response(c) for c in node.children],
    )


# ---------------------------------------------------------------------------
# Category CRUD
# ---------------------------------------------------------------------------

@router.get("/categories")
async def list_categories(format: str = "flat"):
    """List all categories. Use ?format=tree for nested hierarchy."""
    _check_neo4j()
    if format == "tree":
        tree = await neo4j_service.get_category_tree()
        return [_to_response(n) for n in tree]
    else:
        flat = await neo4j_service.get_categories_flat()
        return [_to_response(n) for n in flat]


@router.post("/categories", status_code=201)
async def create_category(req: CategoryCreate):
    _check_neo4j()
    cat = await neo4j_service.create_category(
        name=req.name,
        description=req.description,
        parent_id=req.parent_id,
        sort_order=req.sort_order,
    )
    return _to_response(cat)


@router.put("/categories/{category_id}")
async def update_category(category_id: str, req: CategoryUpdate):
    _check_neo4j()
    updated = await neo4j_service.update_category(
        category_id=category_id,
        name=req.name,
        description=req.description,
        parent_id=req.parent_id,
        sort_order=req.sort_order,
    )
    if not updated:
        raise HTTPException(404, "Category not found")
    return _to_response(updated)


@router.delete("/categories/{category_id}")
async def delete_category(category_id: str):
    _check_neo4j()
    deleted = await neo4j_service.delete_category(category_id)
    if not deleted:
        raise HTTPException(404, "Category not found")
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Source ↔ Category linking
# ---------------------------------------------------------------------------

@router.put("/sources/{source_id}/categories")
async def link_source_categories(source_id: uuid.UUID, req: LinkCategoriesRequest):
    """Assign categories to a source document."""
    _check_neo4j()
    sid = str(source_id)
    await neo4j_service.link_source_to_categories(sid, req.category_ids)
    cats = await neo4j_service.get_source_categories(sid)
    return [_to_response(c) for c in cats]


@router.get("/sources/{source_id}/categories")
async def get_source_categories(source_id: uuid.UUID):
    """Get categories assigned to a source document."""
    _check_neo4j()
    cats = await neo4j_service.get_source_categories(str(source_id))
    return [_to_response(c) for c in cats]


# ---------------------------------------------------------------------------
# Contact ↔ Category linking
# ---------------------------------------------------------------------------

@router.put("/contacts/{contact_id}/categories")
async def link_contact_categories(contact_id: uuid.UUID, req: LinkCategoriesRequest):
    """Assign categories a contact is responsible for."""
    _check_neo4j()
    pid = str(contact_id)
    await neo4j_service.link_contact_to_categories(pid, req.category_ids)
    cats = await neo4j_service.get_contact_categories(pid)
    return [_to_response(c) for c in cats]


@router.get("/contacts/{contact_id}/categories")
async def get_contact_categories(contact_id: uuid.UUID):
    """Get categories a contact is responsible for."""
    _check_neo4j()
    cats = await neo4j_service.get_contact_categories(str(contact_id))
    return [_to_response(c) for c in cats]


# ---------------------------------------------------------------------------
# Knowledge Graph visualization
# ---------------------------------------------------------------------------

@router.get("/graph/overview")
async def graph_overview(limit: int = 300):
    """Get nodes and edges for graph visualization."""
    _check_neo4j()
    return await neo4j_service.get_graph_overview(limit=limit)
