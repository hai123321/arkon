![Arkon Banner](docs/assets/banner.png)

# Arkon

**Enterprise resources management for Ai Client - self-hosted, on-premise.**

Arkon gives organizations centralized control over how employees use any Ai Client. Admins manage resources, access policies, and workspace contexts from a single portal. Employees connect once via the Model Context Protocol (MCP) and get the right context automatically.

---

## The problem

Most organizations adopt Ai team-by-team, group-by-group with no shared resources, inconsistent context, and no visibility into how AI is being used. Every employee manually pastes documents, repeats the same background, and gets different answers depending on what they remembered to include.

Arkon treats Ai Client as a managed organizational resource - not just a personal chatbot.

---

## How it works

When a document is uploaded, Arkon doesn't just index it - it **compiles** it. An LLM reads the document and writes structured knowledge into a persistent wiki: entity pages, concept pages, topic summaries, all interlinked with `[[wikilinks]]`. Each new document updates and enriches the same wiki rather than adding isolated chunks.

When an employee's Claude queries Arkon, it reads from the compiled wiki - synthesized knowledge, not raw fragments. The wiki accumulates and improves with every document added.

```
Upload document
      │
      ▼
[Extract text + images]  ──→  vision captions inlined
      │
      ▼
[LLM Wiki Agent]
  · Reads existing wiki index + searches for related pages
  · Creates / updates wiki pages per source
  · Links concepts via [[wikilinks]], logs changes
      │
      ▼
[Wiki stored in PostgreSQL + pgvector]
  slug, title, content_md, summary
  knowledge_type_slugs[], source_ids[]
  embedding (pgvector)
      │
      ▼
Claude queries via MCP  ──→  reads compiled wiki, not raw chunks
```

---

## Features

### Knowledge Wiki
Upload documents (PDF, DOCX, DOC, spreadsheets, URLs) and an LLM agent compiles them into a structured, interlinked wiki. Knowledge compounds over time - later documents enrich existing wiki pages rather than creating duplicate entries.

- Full **wiki browser** - three-panel layout with page tree, content, backlinks, outlinks, and local graph visualization
- Organize by **knowledge type** (SOP, Product, HR Policy, etc.) - admin-defined with color coding
- Assign documents to **departments** for scoped access
- Background compilation pipeline with real-time progress tracking
- Re-compile any document on demand

### Workspaces
Cross-functional knowledge contexts for initiatives that span multiple departments.

Create a **Workspace** (client engagement, product launch, research project) → add members from any department → attach relevant documents. Each workspace has its own scoped wiki, document list, and member roster. Workspace members access their scoped knowledge automatically through MCP.

- Inline wiki browser per workspace - same three-panel experience as the global wiki
- Inline knowledge graph visualization scoped to workspace documents
- Document upload and management per workspace
- Member management with role assignment

### Access Control (RBAC)
Fine-grained access at department and individual level. When an employee connects via MCP, Arkon resolves their identity, department, and knowledge scope - then filters which wiki pages they can read.

```
Sales dept     → knowledge: product catalog, customer profiles
Support dept   → knowledge: FAQs, troubleshooting SOPs
HR dept        → knowledge: internal policies, org structure
Individual     → personal scope override if needed
```

Wiki pages synthesized from multiple sources inherit the union of their contributing knowledge types - a page is visible if the employee has access to at least one of its types. Workspace membership grants additional access to workspace documents.

### MCP Server
Employees connect Claude Desktop (or any MCP client) to Arkon using a personal token. Claude has three layers of access:

**Wiki layer** - compiled, synthesized knowledge:

| Tool | Description |
|---|---|
| `search_wiki` | Semantic search across the knowledge wiki (RBAC filtered) |
| `read_wiki_index` | Browse the full wiki catalog |
| `read_wiki_page` | Read a specific wiki page with backlinks |
| `list_wiki_pages` | Filter pages by type or knowledge category |

**Source layer** - raw document drill-down for precise citations:

| Tool | Description |
|---|---|
| `list_sources` | Browse uploaded source documents |
| `get_source` | Document metadata and status |
| `get_source_outline` | Table of contents tree (headings-based) |
| `get_source_pages` | Raw text for a specific page range (e.g. `"5-7"`) |

**Directory:**

| Tool | Description |
|---|---|
| `find_contacts` | Search the internal people directory |
| `list_knowledge_types` | Browse knowledge categories |
| `get_knowledge_type_docs` | All documents of a specific category |

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│                  On-Premise Server                │
│                                                   │
│  ┌───────────────┐    ┌────────────────────────┐  │
│  │  Admin Portal │    │    Arkon API + MCP     │  │
│  │               │    │                        │  │
│  │  · Knowledge  │───▶│  · LLM Wiki Agent      │  │
│  │  · Wiki       │    │  · Scope Resolution    │  │
│  │  · RBAC       │    │  · MCP Tool Server     │  │
│  │  · Workspaces │    │  · Auth & Tokens       │  │
│  │  · Contacts   │    │  · Background Worker   │  │
│  └───────────────┘    └───────────┬────────────┘  │
│                                   │               │
└───────────────────────────────────┼───────────────┘
                                    │ MCP (HTTPS)
                       ┌────────────┼────────────┐
                       │            │            │
                Claude Desktop   Claude.ai   Any MCP
                (employees)      (web)       client
```

**Stack:**
- **Backend** - FastAPI, PostgreSQL + pgvector, Redis (arq), MinIO
- **Frontend** - Next.js, Tailwind CSS
- **AI** - provider-agnostic: Google, OpenAI, or Anthropic for embedding, LLM, and vision
- **Outbound** - configured AI provider only. No other external calls.

---

## Getting Started

### Prerequisites

- Docker and Docker Compose
- An API key for your AI provider (Google, OpenAI, or Anthropic)

### 1. Clone and configure

```bash
git clone https://github.com/nduckmink/arkon.git
cd arkon
cp .env.example .env
```

Edit `.env` - at minimum set:

```env
SECRET_KEY=your-random-secret-here
DEFAULT_ADMIN_EMAIL=admin@yourcompany.com
DEFAULT_ADMIN_PASSWORD=change-this-password
```

### 2. Start services

```bash
docker compose up -d
```

This starts PostgreSQL, Redis, MinIO, the API server, the background worker, and the frontend portal.

### 3. Configure AI providers

Open the admin portal at `http://localhost:3000` and log in with the credentials from your `.env`.

Go to **Settings** and configure your embedding model, LLM, and (optionally) vision model. The LLM is used for wiki compilation - choose a model with a large context window (e.g. `gemini-2.5-pro`, `gpt-4o`, `claude-sonnet-4-5`).

### 4. Upload knowledge

Go to **Knowledge Base** and upload your first document. Arkon will extract text, analyze images, and compile the content into your wiki. Progress is shown in real time. Once complete, browse the wiki from the **Wiki** tab.

### 5. Connect an employee to Claude

1. Create a department and employee account in the portal
2. Generate an MCP token for the employee (`Employees → Token`)
3. Add the MCP server to Claude Desktop's config:

```json
{
  "mcpServers": {
    "arkon": {
      "url": "https://your-arkon-server/mcp",
      "headers": {
        "Authorization": "Bearer <employee-mcp-token>"
      }
    }
  }
}
```

The employee opens Claude Desktop - the compiled wiki for their scope is available immediately.

---

## Project Structure

```
arkon/
├── app/
│   ├── routers/          # API endpoints (sources, wiki, rbac, projects, ...)
│   ├── services/         # Auth, MCP auth, wiki CRUD, storage, source outline
│   ├── database/         # SQLAlchemy models, repository, migrations
│   ├── ai/               # Provider-agnostic LLM, embedding, vision + wiki agent
│   ├── mcp/              # MCP server, tools, resources
│   └── worker.py         # Background ingestion + wiki compilation jobs (arq)
├── frontend/
│   └── src/
│       ├── app/(portal)/ # Admin portal pages
│       └── components/   # UI components (wiki, workspaces, knowledge, ...)
└── alembic/              # Database migrations
```

---

## Roadmap

- [x] MCP Server with scoped knowledge access
- [x] Document ingestion pipeline (PDF, DOCX, DOC, URLs, images with vision captions)
- [x] LLM Wiki Agent - documents compiled into persistent, interlinked wiki pages
- [x] Wiki browser - three-panel layout with backlinks, outlinks, and graph visualization
- [x] Workspaces - scoped wiki, documents, and members per project
- [x] Access Control for Admin
- [ ] User wiki contributions - suggest edits, flag outdated content
- [ ] Audit logs and usage analytics
- [ ] Arkon CLI for one-command employee setup

---

## Contributing

Pull requests are welcome. For significant changes, open an issue first to discuss what you'd like to change.

---

## License

Arkon is licensed under the [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0).

You may use, study, and modify Arkon freely for **noncommercial purposes** - internal tooling, research, personal projects, and non-profit use are all fine.

**Need something beyond that?** We help organizations integrate Claude, custom AI agents, and MCP servers into their existing infrastructure and workflows - from connecting to internal databases and legacy systems to building purpose-built agents for specific business processes.

[Get in touch](https://bitsness.vn) if you're looking to build something custom.

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=nduckmink/arkon&type=Date)](https://star-history.com/#nduckmink/arkon&Date)
