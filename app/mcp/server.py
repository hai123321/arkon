"""
Arkon MCP Server — exposes Knowledge Base tools to Claude.

This module creates a FastMCP server that can be mounted into the
main FastAPI app. Claude Desktop connects to /mcp and receives
tools to search knowledge, retrieve documents, list categories, etc.

Architecture:
    Claude Desktop → MCP (HTTPS) → /mcp endpoint → Arkon KB tools
                                                   → PostgreSQL (pgvector)
                                                   → Neo4j (graph)
                                                   → MinIO (files)

Connection:
    Employee runs: arkon connect --server https://ai.company.internal --token <token>
    This adds to Claude Desktop config:
    {
        "mcpServers": {
            "arkon": {
                "url": "https://ai.company.internal/mcp",
                "headers": {"Authorization": "Bearer <token>"}
            }
        }
    }
"""

from fastmcp import FastMCP

from app.mcp.tools import register_tools
from app.mcp.resources import register_resources


def create_mcp_server() -> FastMCP:
    """
    Create and configure the Arkon MCP server.
    Call this once during app startup.
    """
    mcp = FastMCP(
        "Arkon",
        instructions=(
            "You are connected to Arkon — an enterprise Knowledge Base. "
            "Use the available tools to search internal documents, "
            "retrieve specific knowledge, find relevant contacts, "
            "and browse categories. Always cite sources when answering."
        ),
        stateless_http=True,  # Important for multi-replica deployments
    )

    # Register all tools and resources
    register_tools(mcp)
    register_resources(mcp)

    return mcp
