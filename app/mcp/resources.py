"""
Arkon MCP Resources — static/semi-static data exposed to Claude.

Resources provide context that Claude can read at session start,
without needing to call a tool. Think of it as "background knowledge"
that's always available.

Resources:
  - arkon://about: System info and capabilities
  - arkon://categories: Current category structure
"""

from fastmcp import FastMCP
from loguru import logger


def register_resources(mcp: FastMCP):
    """Register MCP resources on the server."""

    @mcp.resource("arkon://about")
    async def about_arkon() -> str:
        """
        About this Arkon instance — capabilities and instructions.
        """
        return (
            "# Arkon Knowledge Base\n\n"
            "You are connected to an Arkon enterprise knowledge base. "
            "This system contains internal documents, SOPs, product information, "
            "and organizational knowledge.\n\n"
            "## Available Tools\n\n"
            "- **search_knowledge**: Search documents by topic or question\n"
            "- **get_document**: Read a specific document in full\n"
            "- **list_sources**: Browse all available documents\n"
            "- **list_categories**: See how knowledge is organized\n"
            "- **find_contacts**: Find people who can help with a topic\n"
            "- **get_category_knowledge**: Browse documents by category\n\n"
            "## Guidelines\n\n"
            "1. Always search before saying you don't know\n"
            "2. Cite sources with document titles and page numbers\n"
            "3. If search returns no results, suggest a contact\n"
            "4. Be clear about what is from documents vs your own knowledge\n"
        )

    @mcp.resource("arkon://categories")
    async def category_overview() -> str:
        """
        Current knowledge category structure.
        """
        from app.services.neo4j_service import neo4j_service

        if not neo4j_service.available:
            return "Categories: Knowledge graph not available."

        try:
            categories = await neo4j_service.list_categories()
            if not categories:
                return "Categories: None defined yet."

            lines = ["# Knowledge Categories\n"]
            for cat in categories:
                name = cat.get("name", "Unnamed")
                doc_count = cat.get("document_count", 0)
                lines.append(f"- {name} ({doc_count} documents)")
            return "\n".join(lines)

        except Exception as e:
            logger.warning(f"Failed to load categories for MCP resource: {e}")
            return "Categories: Failed to load."
