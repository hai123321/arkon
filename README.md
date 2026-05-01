# Arkon

> Enterprise AI Control Center - built exclusively for the Claude ecosystem.

Arkon is a platform that gives organizations centralized control over how employees use Claude. Admins manage knowledge, skills, and access policies from a single portal. Employees connect once and get the right context automatically - no manual configuration, no context switching.

---

## Why Arkon

Most enterprises adopt Claude team-by-team, with no shared knowledge, inconsistent prompting, and no visibility into how AI is being used. Arkon solves this by making Claude a managed, governed resource - like an internal system, not a public chatbot.

---

## Core Features

### 1. Knowledge Base (Graph RAG)

Centralized knowledge built as a graph - not flat documents - so Claude understands relationships between entities, not just keyword matches.

Supported knowledge types:
- **SOPs** - internal processes and procedures
- **Products** - specs, pricing, FAQs
- **Projects** - status, owners, dependencies
- **Customers** - profiles, history, context

Knowledge is retrieved contextually via MCP and injected into Claude's session at query time. Employees never need to paste documents manually.

### 2. Skill Sharing & Sync

Skills are structured packages - not just prompt files. Each skill can contain:

```
skill-package/
├── manifest.json        # ID, version, dependencies, RBAC tags
├── instruction.md       # Core prompt/instruction
├── refs/                # Reference documents
│   ├── tone-guide.md
│   └── product-catalog.json
└── scripts/             # MCP tool definitions (optional)
    └── draft-email.py
```

Admin publishes a skill → employees in the assigned department receive it automatically on next session. No manual download. No re-configuration.

### 3. Access Control (RBAC)

Granular access at both individual and department level.

```
Sales dept        → skill: sales-email-writer, knowledge: customer-profiles
Support dept      → skill: ticket-responder, knowledge: product-faqs
HR dept           → skill: policy-advisor, knowledge: internal-sops
Individual user   → override: additional skills or restricted access
```

Admins control:
- Which skills each department can use
- Which knowledge scopes each role can query
- Version pinning per team (prevent auto-upgrade to breaking versions)
- Revocation and rollback

### 4. Webhook Gateway

Arkon's knowledge base exposes a configurable webhook endpoint - allowing the same knowledge graph to power external touchpoints without duplication.

Use cases:
- **Customer support chatbot** - connects to product and FAQ knowledge
- **Zalo OA** - routes customer queries through the same internal knowledge
- **Any webhook-compatible platform** - configurable per deployment

Each webhook endpoint is independently scoped, authenticated, and rate-limited. Customer-facing endpoints never expose internal SOP or HR knowledge.

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  On-Premise Server               │
│                                                  │
│  ┌──────────────┐    ┌──────────────────────┐   │
│  │ Admin Portal │    │   Arkon MCP Server   │   │
│  │              │    │                      │   │
│  │ · Skills     │───▶│ · Skill Registry     │   │
│  │ · Knowledge  │    │ · Knowledge Graph    │   │
│  │ · RBAC       │    │ · Auth & Policy      │   │
│  │ · Versions   │    │ · Webhook Gateway    │   │
│  └──────────────┘    └──────────┬───────────┘   │
│                                 │                │
└─────────────────────────────────┼────────────────┘
                                  │ MCP (HTTPS)
                    ┌─────────────┼─────────────┐
                    │             │             │
             Claude Desktop  Claude.ai     Other MCP
             (employee)      (web)         clients
```

---

## How Employees Connect

One-time setup. Employees run the Arkon installer provided by their IT admin:

```bash
# Arkon CLI - auto-configures Claude Desktop
arkon connect --server https://ai.company.internal --token <employee-token>
```

This adds the MCP server to Claude Desktop config automatically:

```json
{
  "mcpServers": {
    "arkon": {
      "url": "https://ai.company.internal/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

After this, employees open Claude Desktop as usual. Skills and knowledge for their department are available immediately - no further action required.

---

## Skill Lifecycle

```
Admin uploads skill v2.0
        ↓
Arkon registry updates
        ↓
Employee opens new conversation
        ↓
MCP server resolves: user → dept → skills → latest version
        ↓
Skill injected into context automatically
```

Admins can configure update policy per skill:
- `auto` - always serve latest version
- `pinned` - lock a department to a specific version
- `manual` - require admin approval before rollout

---

## Deployment

Arkon is designed for on-premise deployment inside the customer's network. All data stays within the organization's infrastructure.

**Requirements:**
- Docker / Docker Compose
- HTTPS endpoint accessible from employee machines
- Claude API key (Anthropic)

**External calls:**
- Claude API (Anthropic) - for LLM inference only
- No other outbound dependencies

---

## Roadmap

- [x] MCP Server core
- [x] Knowledge Base (Graph RAG) via MCP
- [x] Skill Registry with versioning
- [x] RBAC (individual + department)
- [x] Webhook Gateway
- [x] Admin Portal UI
- [ ] Arkon CLI installer
- [ ] Staff Contributing
- [ ] Audit logs & usage analytics
- [ ] SSO integration (Active Directory / Google Workspace)
- [ ] Any other ideas that came up at 3 a.m

---

## License

Arkon is licensed under the [PolyForm Noncommercial License 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0).

You may use, study, and modify Arkon for **noncommercial purposes** only. Commercial use - including deploying Arkon as part of a paid product or service, or using it within a for-profit organization - requires a separate commercial license.

Contact us for commercial licensing and enterprise deployment options.