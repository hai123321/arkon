"""
Arkon — Enterprise AI Control Center.
FastAPI application entry point.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import settings
from app.mcp.server import create_mcp_server


# Create the MCP server instance (shared across the app lifecycle)
mcp_server = create_mcp_server()


async def seed_default_admin():
    """Create default admin account from .env if no admin exists yet."""
    from sqlalchemy import select
    from app.database import async_session_factory
    from app.database.models import Department, Employee
    from app.services.auth_service import hash_password

    try:
        async with async_session_factory() as session:
            # Check if any admin already exists
            stmt = select(Employee).where(Employee.role == "admin").limit(1)
            result = await session.execute(stmt)
            if result.scalar_one_or_none():
                return  # Admin already exists, skip

            # Create admin department
            dept = Department(name="Administration", description="System administrators")
            session.add(dept)
            await session.flush()

            # Create admin user from .env
            admin = Employee(
                name="Admin",
                email=settings.default_admin_email,
                password_hash=hash_password(settings.default_admin_password),
                role="admin",
                department_id=dept.id,
            )
            session.add(admin)
            await session.commit()
            logger.success(f"Default admin created: {settings.default_admin_email}")
    except Exception as e:
        logger.warning(f"Could not seed default admin: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup & shutdown logic."""
    logger.info("Starting Arkon API...")

    # Ensure MinIO bucket exists
    try:
        from app.services.storage_service import storage_service
        await storage_service.ensure_bucket()
        logger.success("MinIO bucket ready")
    except Exception as e:
        logger.warning(f"MinIO not available yet: {e}")

    # Connect Neo4j Knowledge Graph
    try:
        from app.services.neo4j_service import neo4j_service
        await neo4j_service.connect()
    except Exception as e:
        logger.warning(f"Neo4j not available: {e}")

    # Seed default admin if no admin exists yet
    await seed_default_admin()

    # Start MCP session manager
    async with mcp_server.session_manager.run():
        logger.success("Arkon MCP Server ready at /mcp")
        logger.success("Arkon API started successfully")
        yield

    # Shutdown Neo4j
    try:
        from app.services.neo4j_service import neo4j_service
        await neo4j_service.close()
    except Exception:
        pass
    logger.info("Arkon API shutdown complete")


app = FastAPI(
    title="Arkon API",
    description="Enterprise AI Control Center — Knowledge Base & Skill Management",
    version="0.1.0",
    lifespan=lifespan,
)

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Mount MCP Server ---
# Claude Desktop connects to: https://your-server/mcp
app.mount("/mcp", mcp_server.streamable_http_app())

# --- REST API Routers ---
from app.routers import sources, notes, contacts, search, auth, admin_settings, categories, rbac, knowledge_types  # noqa: E402

app.include_router(auth.router, prefix="/api", tags=["auth"])
app.include_router(sources.router, prefix="/api", tags=["sources"])
app.include_router(notes.router, prefix="/api", tags=["notes"])
app.include_router(contacts.router, prefix="/api", tags=["contacts"])
app.include_router(categories.router, prefix="/api", tags=["categories"])
app.include_router(search.router, prefix="/api", tags=["search"])
app.include_router(admin_settings.router, prefix="/api", tags=["settings"])
app.include_router(rbac.router, prefix="/api", tags=["rbac"])
app.include_router(knowledge_types.router, prefix="/api", tags=["knowledge-types"])


@app.get("/")
async def root():
    return {
        "name": "Arkon",
        "description": "Enterprise AI Control Center",
        "version": "0.1.0",
        "mcp_endpoint": "/mcp",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}
