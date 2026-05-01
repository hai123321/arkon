"""
Search router — semantic search across the knowledge base.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.kb_service import search_kb, suggest_contacts

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10
    min_similarity: float = 0.2


class SearchResultItem(BaseModel):
    source_title: Optional[str]
    content: str
    similarity: float
    page_number: Optional[int]
    image_urls: list[str]
    source_download_url: Optional[str]


class ContactSuggestion(BaseModel):
    name: str
    role: Optional[str]
    phone: Optional[str]
    email: Optional[str]


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    contacts: list[ContactSuggestion]
    message: Optional[str] = None


@router.post("/search", response_model=SearchResponse)
async def search_knowledge_base(req: SearchRequest, db: AsyncSession = Depends(get_db)):
    """
    Semantic search across the knowledge base.
    If no results found, suggests relevant contacts.
    """
    results = await search_kb(db, req.query, top_k=req.top_k, min_similarity=req.min_similarity)

    items = [
        SearchResultItem(
            source_title=r.source_title,
            content=r.content,
            similarity=r.similarity,
            page_number=r.page_number,
            image_urls=r.image_urls,
            source_download_url=r.source_download_url,
        )
        for r in results
    ]

    # If no results, suggest contacts
    contacts: list[ContactSuggestion] = []
    message = None
    if not items:
        contact_data = await suggest_contacts(db, req.query)
        contacts = [ContactSuggestion(**c) for c in contact_data]
        if contacts:
            message = "Không tìm thấy thông tin trong tài liệu. Đề xuất liên hệ:"
        else:
            message = "Không tìm thấy thông tin liên quan trong hệ thống."

    return SearchResponse(results=items, contacts=contacts, message=message)
