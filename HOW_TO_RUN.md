# Arkon — How to Run (Development)

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11 — 3.12 | Backend runtime |
| PostgreSQL | 15+ | Main database (with pgvector extension) |
| Redis | 7+ | Background job queue |
| MinIO | Latest | S3-compatible file storage |
| Neo4j | 5+ | Knowledge graph (optional) |
| Node.js | 20+ | Frontend (when ready) |

## 1. Infrastructure

Start PostgreSQL, Redis, MinIO, Neo4j. If you have Docker:

```bash
# PostgreSQL with pgvector
docker run -d --name arkon-pg \
  -e POSTGRES_USER=arkon \
  -e POSTGRES_PASSWORD=arkon_secret \
  -e POSTGRES_DB=arkon \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# Redis
docker run -d --name arkon-redis -p 6379:6379 redis:7-alpine

# MinIO
docker run -d --name arkon-minio \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin123 \
  -p 9000:9000 -p 9001:9001 \
  minio/minio server /data --console-address ":9001"

# Neo4j (optional — only if ENABLE_ENTITY_EXTRACTION=true)
docker run -d --name arkon-neo4j \
  -e NEO4J_AUTH=neo4j/your-neo4j-password \
  -p 7474:7474 -p 7687:7687 \
  neo4j:5
```

## 2. Environment

```bash
# Copy env template
cp .env.example .env

# Edit .env — set your values:
#   SECRET_KEY           → generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
#   DEFAULT_ADMIN_EMAIL  → email for initial admin account
#   DEFAULT_ADMIN_PASSWORD → password for initial admin account
#   MINIO_SECRET_KEY     → match your MinIO password
#   NEO4J_PASSWORD       → match your Neo4j password (if using)
```

## 3. Install Dependencies

```bash
# Create virtual environment
python -m venv .venv

# Activate
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

# Install all dependencies
pip install -e ".[dev]"
```

## 4. Database Migration

```bash
# Run migrations (creates all tables)
alembic upgrade head
```

> Migration creates: `sources`, `source_chunks`, `source_insights`, `chunk_images`,
> `knowledge_types`, `departments`, `employees`, `knowledge_scopes`,
> `contacts`, `notes`, `admin_configs`
>
> Also seeds 5 default knowledge types: General, SOP, Product, Project, Customer.

## 5. Start Backend

You need **2 terminals** — one for the API, one for the background worker.

### Terminal 1: API Server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 5055 --reload
```

On first startup, Arkon will:
- Create the MinIO bucket if it doesn't exist
- Connect to Neo4j (if available)
- **Auto-create the default admin account** from `.env` (if no admin exists yet)

You should see:
```
SUCCESS  Default admin created: admin@arkon.local
SUCCESS  Arkon MCP Server ready at /mcp
SUCCESS  Arkon API started successfully
```

### Terminal 2: Background Worker

```bash
python -m arq app.worker.WorkerSettings
```

The worker processes document ingestion (chunking, embedding, entity extraction).

## 6. Verify

### API Health

```
http://localhost:5055/
```

### API Docs (Swagger)

```
http://localhost:5055/docs
```

### Login

```bash
curl -X POST http://localhost:5055/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@arkon.local", "password": "admin123"}'
```

Response:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": "...",
    "name": "Admin",
    "email": "admin@arkon.local",
    "role": "admin"
  }
}
```

Use the `access_token` as `Authorization: Bearer <token>` for all admin API calls.

## 7. API Overview

### Auth (public)
| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/login` | Login (email + password) |
| GET | `/api/auth/me` | Current user profile |
| POST | `/api/auth/change-password` | Change password |

### Admin (requires role=admin)
| Method | Path | Description |
|---|---|---|
| GET/PUT | `/api/settings` | Provider config (AI keys, models) |
| CRUD | `/api/departments` | Manage departments |
| CRUD | `/api/employees` | Manage employees |
| POST/DELETE | `/api/employees/:id/token` | Generate/revoke MCP token |
| CRUD | `/api/knowledge-types` | Manage knowledge types |
| CRUD | `/api/scopes` | Manage knowledge scopes |
| CRUD | `/api/sources` | Manage documents |
| CRUD | `/api/contacts` | Manage contacts |

### Employee (requires login)
| Method | Path | Description |
|---|---|---|
| POST | `/api/my/mcp-token` | Get own MCP token |
| DELETE | `/api/my/mcp-token` | Revoke own MCP token |
| POST | `/api/search` | Search knowledge base |

### MCP (Claude Desktop)
| Path | Auth | Description |
|---|---|---|
| `/mcp` | `Bearer ark_xxx` (MCP token) | MCP endpoint for Claude Desktop |

## 8. Connect Claude Desktop

After generating an MCP token for an employee, add to Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "arkon": {
      "url": "http://localhost:5055/mcp",
      "headers": {
        "Authorization": "Bearer ark_xxxx..."
      }
    }
  }
}
```

## 9. Configure AI Providers

After first login, go to API or Admin Portal to configure:

```bash
# Set embedding provider (required for document ingestion)
curl -X PUT http://localhost:5055/api/settings \
  -H "Authorization: Bearer <admin-jwt>" \
  -H "Content-Type: application/json" \
  -d '{
    "embedding_provider": "google",
    "embedding_model": "text-embedding-004",
    "embedding_api_key": "your-google-api-key"
  }'
```

Without embedding config, document uploads will fail at the chunking/embedding step.

## Troubleshooting

| Issue | Solution |
|---|---|
| `connection refused` on port 5432 | PostgreSQL is not running |
| `pgvector extension not found` | Use `pgvector/pgvector` Docker image, or install pgvector manually |
| `No admin created` on startup | Check `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` in `.env` |
| Documents stuck at `processing` | Worker is not running — start Terminal 2 |
| `Neo4j not available` warning | Normal if `ENABLE_ENTITY_EXTRACTION=false` |
