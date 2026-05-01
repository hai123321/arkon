"""
Knowledge Base service — document ingestion, chunking, embedding, search.
This is the core pipeline: Upload → Extract → Chunk → Embed → Store.

Provider-agnostic: uses ProviderRegistry to resolve the configured
embedding, LLM, and vision providers at runtime.
"""

import uuid
from dataclasses import dataclass
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.registry import ProviderRegistry
from app.config import settings
from app.database.models import ChunkImage, Contact, Source, SourceChunk, SourceInsight
from app.database.vector_search import SearchResult, semantic_search
from app.services.image_service import ImageInfo, extract_images
from app.services.storage_service import storage_service


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------

def chunk_text_with_pages(
    pages_data: list[dict],
    chunk_size: int = 1500,
    chunk_overlap: int = 150,
) -> list[dict]:
    """
    Split text into overlapping chunks while tracking page numbers.
    Returns: [{"content": str, "page_number": int}, ...]
    """
    if not pages_data:
        return []

    chunks = []
    
    for page in pages_data:
        text = page["content"].strip()
        page_num = page.get("page_number")
        
        if not text:
            continue
            
        start = 0
        text_len = len(text)
        
        while start < text_len:
            end = min(start + chunk_size, text_len)
            
            # Try to find a good break point (paragraph > sentence > word)
            if end < text_len:
                para_break = text.rfind("\n\n", start + chunk_size // 2, end)
                if para_break > start:
                    end = para_break + 2
                else:
                    for sep in [". ", ".\n", "? ", "! "]:
                        sent_break = text.rfind(sep, start + chunk_size // 2, end)
                        if sent_break > start:
                            end = sent_break + len(sep)
                            break
                            
            chunk_content = text[start:end].strip()
            if chunk_content:
                chunks.append({
                    "content": chunk_content,
                    "page_number": page_num
                })
                
            start = end - chunk_overlap if end < text_len else text_len
            
    return chunks


# ---------------------------------------------------------------------------
# Image-to-chunk mapping
# ---------------------------------------------------------------------------

def map_images_to_chunks(
    images: list[ImageInfo],
    chunks: list[dict],
) -> dict[int, list[ImageInfo]]:
    """
    Map extracted images to chunk indices EXACTLY based on page numbers.
    Returns: {chunk_index: [ImageInfo, ...]}
    """
    if not images or not chunks:
        return {}

    mapping: dict[int, list[ImageInfo]] = {}

    # Group chunks by page_number
    page_to_chunk_indices = {}
    for i, chunk in enumerate(chunks):
        pnum = chunk.get("page_number")
        if pnum is not None:
            page_to_chunk_indices.setdefault(pnum, []).append(i)

    for img in images:
        if img.page_number is not None and img.page_number in page_to_chunk_indices:
            # Associate the image with ALL chunks on this page so it is retrieved
            # with any matching text from that page.
            for chunk_idx in page_to_chunk_indices[img.page_number]:
                mapping.setdefault(chunk_idx, []).append(img)
        else:
            # Fallback if image has no page number (or page not found)
            if chunks:
                mapping.setdefault(0, []).append(img)

    return mapping


# ---------------------------------------------------------------------------
# Ingestion pipeline
# ---------------------------------------------------------------------------

async def ingest_source(
    session: AsyncSession,
    source_id: uuid.UUID,
    file_data: Optional[bytes] = None,
    file_name: Optional[str] = None,
) -> Source:
    """
    Full ingestion pipeline:
    1. Upload original file to MinIO
    2. Extract text content
    3. Extract images from PDF/DOCX
    4. Chunk text
    5. Generate embeddings via Gemini
    6. Store chunks + images in PostgreSQL
    7. Generate source summary
    """
    source = await session.get(Source, source_id)
    if not source:
        raise ValueError(f"Source {source_id} not found")

    try:
        # Resolve AI providers from DB config
        registry = ProviderRegistry(session)
        embedding_provider = await registry.get_embedding(task="document")
        vision_provider = await registry.get_vision()

        # Update status
        source.status = "processing"
        await session.flush()

        # --- Step 1: Upload original file to MinIO ---
        if file_data and file_name:
            minio_key = f"sources/{source_id}/original/{file_name}"
            storage_service.upload_file(
                object_name=minio_key,
                data=file_data,
                content_type=_guess_content_type(file_name),
            )
            source.minio_key = minio_key
            source.file_name = file_name
            source.file_size = len(file_data)
            logger.info(f"Uploaded original file to MinIO: {minio_key}")

        # --- Step 2: Extract text ---
        if file_data and file_name:
            pages_data = await _extract_text_from_file(file_data, file_name)
        elif source.url:
            pages_data = await _extract_text_from_url(source.url)
        else:
            pages_data = []

        text_content = "\n\n".join([p["content"] for p in pages_data])

        if not text_content or not text_content.strip():
            source.status = "error"
            source.error_message = "Could not extract text content from source"
            await session.flush()
            return source

        source.full_text = text_content

        # --- Step 3: Extract images & Vision analysis ---
        images: list[ImageInfo] = []
        if file_data and file_name:
            images = extract_images(file_data, file_name, str(source_id))
            if vision_provider:
                for idx, img in enumerate(images, 1):
                    try:
                        if idx % 5 == 0 or idx == 1 or idx == len(images):
                            logger.info(f"Vision AI analyzing image {idx}/{len(images)}...")

                        img_bytes = storage_service.download_file(img.minio_key)
                        mime_type = "image/jpeg"
                        if img.minio_key.lower().endswith(".png"):
                            mime_type = "image/png"
                        img.caption = await vision_provider.analyze_image(img_bytes, mime_type)
                    except Exception as e:
                        logger.warning(f"Failed to analyze image {img.minio_key}: {e}")
            else:
                logger.info("No vision provider configured, skipping image analysis")

        # --- Step 4: Chunk text ---
        chunks_data = chunk_text_with_pages(
            pages_data,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )
        logger.info(f"Source {source_id}: {len(chunks_data)} chunks, {len(images)} images")

        # --- Step 4.5: Image Mapping and Semantic Injection ---
        image_mapping = map_images_to_chunks(images, chunks_data)

        chunk_texts_to_embed = []
        for i, chunk in enumerate(chunks_data):
            chunk_text = chunk["content"]
            chunk_images = image_mapping.get(i, [])
            captions = [img.caption for img in chunk_images if img.caption]
            if captions:
                chunk_text += "\n\n[IMAGE DESCRIPTIONS ON THIS PAGE:]\n" + "\n".join(captions)
            chunk_texts_to_embed.append(chunk_text)

        # --- Step 5: Generate embeddings (provider-agnostic) ---
        embeddings = await embedding_provider.embed_batch(chunk_texts_to_embed)

        # --- Step 6: Store chunks + images ---
        for i, (chunk_dict, embedding, full_chunk_text) in enumerate(zip(chunks_data, embeddings, chunk_texts_to_embed)):
            chunk_obj = SourceChunk(
                source_id=source_id,
                content=full_chunk_text,
                embedding=embedding,
                chunk_index=i,
                page_number=chunk_dict.get("page_number")
            )
            session.add(chunk_obj)
            await session.flush()

            # Store associated images
            chunk_images = image_mapping.get(i, [])
            for img in chunk_images:
                img_obj = ChunkImage(
                    chunk_id=chunk_obj.id,
                    source_id=source_id,
                    minio_key=img.minio_key,
                    page_number=img.page_number,
                    image_index=img.image_index,
                    caption=img.caption,
                )
                session.add(img_obj)

        # Store images without chunk mapping (leftover)
        all_mapped_images = {
            img.minio_key for imgs in image_mapping.values() for img in imgs
        }
        for img in images:
            if img.minio_key not in all_mapped_images:
                img_obj = ChunkImage(
                    chunk_id=None,
                    source_id=source_id,
                    minio_key=img.minio_key,
                    page_number=img.page_number,
                    image_index=img.image_index,
                )
                session.add(img_obj)

        # --- Step 7: Generate summary insight (provider-agnostic) ---
        try:
            llm = await registry.get_llm()
            summary = await llm.generate(
                f"Summarize this document concisely (max 500 words):\n\n{text_content[:10000]}",
                temperature=0.3,
                max_tokens=1024,
            )
            insight = SourceInsight(
                source_id=source_id,
                insight_type="summary",
                content=summary,
            )
            session.add(insight)
        except Exception as e:
            logger.warning(f"Failed to generate summary: {e}")

        source.status = "ready"
        source.error_message = None
        await session.flush()
        logger.success(f"Source {source_id} ingested: {len(chunks_data)} chunks, {len(images)} images")
        return source

    except Exception as e:
        logger.error(f"Ingestion failed for source {source_id}: {e}")
        source.status = "error"
        source.error_message = str(e)[:500]
        await session.flush()
        raise


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@dataclass
class KBSearchResult:
    """A KB search result with presigned URLs."""
    source_title: Optional[str]
    content: str
    similarity: float
    page_number: Optional[int]
    image_urls: list[str]
    source_download_url: Optional[str]
    source_id: uuid.UUID


async def search_kb(
    session: AsyncSession,
    query: str,
    top_k: int = 10,
    min_similarity: float = 0.2,
) -> list[KBSearchResult]:
    """
    Semantic search across the knowledge base.
    Returns results with presigned image URLs and source download links.
    """
    # Embed the query using configured provider (with search_query task)
    registry = ProviderRegistry(session)
    embedding_provider = await registry.get_embedding(task="search_query")
    query_embedding = await embedding_provider.embed(query)

    # pgvector search
    results = await semantic_search(
        session=session,
        query_embedding=query_embedding,
        top_k=top_k,
        min_similarity=min_similarity,
    )

    # Enrich with presigned URLs
    kb_results: list[KBSearchResult] = []
    for r in results:
        # Generate presigned URLs for images
        image_urls = []
        for key in r.image_keys:
            try:
                url = storage_service.get_presigned_url(key)
                image_urls.append(url)
            except Exception:
                pass

        # Get source download URL
        source_download_url = None
        source = await session.get(Source, r.source_id)
        if source and source.minio_key:
            try:
                source_download_url = storage_service.get_presigned_url(source.minio_key)
            except Exception:
                pass

        kb_results.append(KBSearchResult(
            source_title=r.source_title,
            content=r.content,
            similarity=r.similarity,
            page_number=r.page_number,
            image_urls=image_urls,
            source_download_url=source_download_url,
            source_id=r.source_id,
        ))

    return kb_results


async def get_context_for_chat(
    session: AsyncSession,
    query: str,
    top_k: int = 5,
) -> tuple[str, list[str], Optional[str]]:
    """
    Search KB and format context for chat.
    Returns: (context_text, image_urls, source_download_url)
    """
    results = await search_kb(session, query, top_k=top_k)

    if not results:
        return "", [], None

    # Build context string
    context_parts = []
    all_image_urls: list[str] = []
    source_url = None

    for r in results:
        source_label = f"[{r.source_title}]" if r.source_title else ""
        page_label = f" (trang {r.page_number})" if r.page_number else ""
        context_parts.append(f"--- {source_label}{page_label} ---\n{r.content}")
        all_image_urls.extend(r.image_urls)
        if not source_url and r.source_download_url:
            source_url = r.source_download_url

    context = "\n\n".join(context_parts)
    return context, all_image_urls, source_url


# ---------------------------------------------------------------------------
# Contact suggestion fallback
# ---------------------------------------------------------------------------

async def suggest_contacts(
    session: AsyncSession,
    query: str,
    limit: int = 3,
) -> list[dict]:
    """
    Find relevant contacts based on query keywords matching topics.
    Used when KB search returns no results.
    """
    # Simple keyword matching against contact topics
    stmt = select(Contact).where(Contact.topics.isnot(None))
    result = await session.execute(stmt)
    contacts = result.scalars().all()

    query_lower = query.lower()
    scored = []
    for c in contacts:
        if not c.topics:
            continue
        score = sum(1 for t in c.topics if t.lower() in query_lower or query_lower in t.lower())
        if score > 0:
            scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "name": c.name,
            "role": c.role,
            "phone": c.phone,
            "email": c.email,
        }
        for _, c in scored[:limit]
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _guess_content_type(file_name: str) -> str:
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "txt": "text/plain",
        "md": "text/markdown",
        "csv": "text/csv",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }.get(ext, "application/octet-stream")


async def _extract_text_from_file(file_data: bytes, file_name: str) -> list[dict]:
    """Extract text content from uploaded file, preserving page numbers."""
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""

    pages_data = []

    if ext == "pdf":
        import fitz
        doc = fitz.open(stream=file_data, filetype="pdf")
        for i, page in enumerate(doc):
            text = page.get_text()
            pages_data.append({
                "content": text.strip(),
                "page_number": i + 1
            })
        doc.close()
        return pages_data

    elif ext in ("docx",):
        import io
        from docx import Document
        doc = Document(io.BytesIO(file_data))
        text = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
        pages_data.append({"content": text, "page_number": 1})
        return pages_data

    elif ext in ("txt", "md", "csv"):
        text = file_data.decode("utf-8", errors="ignore")
        pages_data.append({"content": text, "page_number": 1})
        return pages_data

    else:
        # Try content-core for other formats
        try:
            from content_core import extract_content
            result = await extract_content({
                "file_path": None,
                "content": file_data,
                "output_format": "markdown",
            })
            pages_data.append({"content": result.content or "", "page_number": 1})
            return pages_data
        except Exception as e:
            logger.warning(f"content-core extraction failed: {e}")
            text = file_data.decode("utf-8", errors="ignore")
            pages_data.append({"content": text, "page_number": 1})
            return pages_data


async def _extract_text_from_url(url: str) -> list[dict]:
    """Extract text content from a URL."""
    try:
        from content_core import extract_content
        result = await extract_content({
            "url": url,
            "output_format": "markdown",
        })
        return [{"content": result.content or "", "page_number": 1}]
    except Exception as e:
        logger.warning(f"URL extraction failed for {url}: {e}")
        # Fallback: simple HTTP fetch
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, follow_redirects=True, timeout=30)
            return [{"content": resp.text, "page_number": 1}]
