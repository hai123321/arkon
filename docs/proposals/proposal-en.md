# Master Design Vault — A "Second Brain" Proposal for the Bank

> **Author**: Hai Trieu — Solutions Architect
> **Date**: 2026-05-05
> **Version**: 2.0 (split into two MVPs)
> **Audience**: Brain Owner & Technology Leadership

---

## 1. Executive Summary (TL;DR)

The bank operates **dozens of large systems** (core banking, payments, lending, channels…). Design docs are scattered across Confluence, Word, email, and the heads of senior architects. **Every production deploy widens the gap between code and docs.**

**Proposal**: Build a **Master Design Vault** — the bank's centralized, version-controlled documentation repository that serves as a "second brain" for every developer. Delivered in **two MVPs**:

| | **MVP 1 — Foundation** | **MVP 2 — End-state** |
|---|---|---|
| **Shape** | GitLab markdown repo + Kiro local | Arkon + AWS Bedrock + MCP + auto-ingest |
| **Primary goal** | Validate value, build the doc-writing habit | Automate, scale across the bank |
| **Timeline** | 4-6 weeks | +8-12 weeks after MVP 1 |
| **Investment** | ~$3K (mostly internal) | ~$9K (incl. Bedrock + customization) |
| **Risk** | 🟢 Low — no new infrastructure | 🟡 Medium — new stack to deploy |
| **Compliance dependency** | None (data stays in internal Git) | Enable Bedrock access (1-2 days) |

**Why split**: MVP 1 proves the **human side** (developers actually use it, docs actually get maintained) **before** investing in automation. If MVP 1 fails to drive adoption → stop, no further spend. If MVP 1 succeeds → MVP 2 is a natural scale-up.

---

## 2. Problem Statement

### 2.1 Knowledge fragmentation today

```
   Confluence ──┐                ┌── Email threads
                │                │
   Word docs ───┼─→ ❓ ←─────────┤
                │  Senior         │
   Jira ────────┤  architect     ├── Slack messages
                │  (in head)     │
   GitLab MR ───┘                └── Personal notes

   → No single source of truth
   → Code ships → docs do NOT update → drift compounds
```

### 2.2 Banking-specific risks

- **Compliance**: Audits require proving "code A matches design B" — currently a manual scramble
- **Senior departure risk**: Knowledge of core banking integration walks out the door
- **Incident response**: Locating architecture specs during a prod incident takes 30+ minutes
- **Decision drift**: 6 months later, no one remembers why pattern X was chosen
- **Cross-team duplication**: Teams A and B solve the same problem unaware of each other

---

## 3. MVP 1 — Foundation (Weeks 1-6)

### 3.1 Philosophy

> **"Get the habit first, automate later."**
>
> The biggest blocker isn't technical — it's the **doc-writing culture**. MVP 1 deliberately keeps the stack as simple as possible so we focus 100% on building the habit: "code merges → update the doc → commit → review."

### 3.2 Architecture

```
┌──────────────────────────────────────────────────────────┐
│  Layer 1 — VAULT (GitLab repo, plain markdown)           │
├──────────────────────────────────────────────────────────┤
│  master-design/                                           │
│  ├── _index.md               ← TOC (human-written)       │
│  ├── systems/                                             │
│  │   ├── core-banking/                                    │
│  │   │   ├── overview.md                                  │
│  │   │   ├── api-contracts.md                             │
│  │   │   ├── integrations.md                              │
│  │   │   └── decisions/  ← ADR for every major decision  │
│  │   ├── payment-gateway/                                 │
│  │   └── ...                                              │
│  ├── cross-cutting/        ← auth, logging, security     │
│  └── CONTRIBUTING.md       ← Doc-writing rules           │
└──────────────────────────┬───────────────────────────────┘
                           │ git clone / git pull
                           ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 2 — INTERACTION (Kiro IDE local, per engineer)    │
├──────────────────────────────────────────────────────────┤
│  • Each engineer clones the vault alongside project repo │
│  • Kiro is configured to point at the vault via steering │
│  • Natural-language queries:                              │
│    "How does Payment call Core Banking?"                 │
│    → Kiro reads the vault markdown, answers + cites file │
│  • When writing new specs: Kiro auto-references old docs │
└──────────────────────────────────────────────────────────┘
```

**That's it.** No server. No AI pipeline. No MCP. No auto-ingest. As simple as possible.

### 3.3 Operating workflow

```
1. Create `master-design` GitLab repo in the bank's namespace
2. Brain Owner writes CONTRIBUTING.md + skeleton _index.md
3. Each team contributes initial content:
   ├─ Each pilot system → 1 folder, seed 3-5 core MD files
   └─ Each new architecture decision → 1 ADR file in decisions/
4. Engineer daily workflow:
   ├─ Clone vault alongside code repo
   ├─ Kiro is pointed at the vault via steering
   └─ Ask Kiro anything — it reads the filesystem directly
5. When shipping code to prod:
   ├─ Engineer (or tech lead) opens an MR updating the vault
   └─ Brain Owner reviews + approves the MR
```

### 3.4 In scope / out of scope

| ✅ In scope (MVP 1) | ❌ Out of scope (defer to MVP 2) |
|---|---|
| GitLab markdown repo | AI auto-generating docs from code |
| Index, ADRs, system overview | MCP server for team-wide query |
| Kiro local reading filesystem | Auto-ingest from Confluence |
| Manual MR review | Automatic conflict detection |
| Pilot on 1-2 systems | Cover all ~50 systems |
| 5-10 engineers using it | 200+ engineers onboarded |

### 3.5 MVP 1 cost

| Item | Calculation | $ |
|---|---|---|
| Brain Owner (Tech Lead, part-time) | $2,500/mo × 25% × 6 weeks | ~$900 |
| 2 engineers seeding docs (part-time) | $2,000/mo × 20% × 6 weeks × 2 | ~$1,200 |
| Kiro license (5-10 pilot users) | Per team pricing | ~$300-600 |
| Infrastructure | GitLab already in place | $0 |
| Buffer | | ~$200 |
| **Total** | | **~$3K** |

**Fresh budget required**: only the Kiro license (~$300-600). Everything else is **internal opportunity cost**.

### 3.6 MVP 1 success criteria

Measured at week 6:

- ✅ **80% of pilot engineers** have committed at least 1 MR to the vault
- ✅ **≥20 ADRs** written for decisions made during the 6 weeks
- ✅ **≥80% of "why X?" questions** answerable in <2 minutes via Kiro
- ✅ **≥1 case study** where the vault visibly helped resolve an incident or accelerated onboarding
- ✅ Brain Owner confirms: "I want to continue scaling this" — this is the gate decision for MVP 2

**If fewer than 3/5 criteria are met**: stop. We've saved most of the budget vs. a big-bang approach.

---

## 4. MVP 2 — End-state (Weeks 7-18)

### 4.1 Philosophy

> **"Automate what humans already proved valuable."**
>
> MVP 2 only starts after MVP 1 has demonstrated value. Investing in automation is then safe because we have real usage data backing the decision.

### 4.2 End-state architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  📥 LAYER 1 — DATA SOURCES                                      │
│  GitLab · Jira · Confluence · API contracts · DB schemas · ADRs │
└──────────────────────────┬──────────────────────────────────────┘
                           │ webhooks + post-deploy hooks
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  🧠 LAYER 2 — AI PIPELINE (Arkon on AWS, in-VPC)                │
│  • Change Management Process triggers after prod deploy         │
│  • Diff extractor                                               │
│  • PII/PCI redactor (defense-in-depth)                          │
│  • Claude on AWS Bedrock — no data egress                       │
│  • MRP pipeline: MAP → REDUCE → PLAN → REFINE → VERIFY          │
│  • CloudTrail audit log on every Bedrock invocation             │
└──────────────────────────┬──────────────────────────────────────┘
                           │ creates MR (NO auto-merge)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  📚 LAYER 3 — VAULT (inherited from MVP 1)                      │
│  • GitLab markdown repo (same as MVP 1)                         │
│  • Adds: AI-generated entries via MR                            │
│  • Brain Owner reviews MRs — human-in-the-loop mandatory        │
│  • Conflict log when AI detects contradictions                  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ git pull (locally) · MCP (for query) │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  💻 LAYER 4 — INTERACTION                                       │
│  • Kiro local (inherited from MVP 1)                            │
│  • Arkon MCP for Claude Desktop / Claude.ai (team-wide query)   │
│  • RBAC-scoped — each user sees only their permitted scope      │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 Technology stack

| Layer | Technology | Why |
|---|---|---|
| Base platform | **Arkon** (fork of github.com/hai123321/arkon) | Already provides MRP pipeline, MCP, RBAC, draft workflow — saves ~80% of build-from-scratch effort |
| AI engine | **Claude (Sonnet/Haiku) on AWS Bedrock** | Data stays in VPC, compliance-ready |
| Vault | GitLab markdown repo (inherited from MVP 1) + Arkon DB | Humans still browse via Git; MCP queries via Arkon |
| Audit | AWS CloudTrail + CloudWatch + Git history | Triple audit trail |
| Confluence migration | `tools/confluence-migration/migrate.py` (one-time CLI, already built) | One-time bulk import from existing Confluence |
| Interaction | Kiro IDE (local) + Claude Desktop (MCP) | Covers both developers and non-devs (BA, PM) |

### 4.4 MVP 2 timeline

```
Weeks 7-8    │ Foundation
             │ • Deploy Arkon on AWS (docker-compose or ECS)
             │ • Implement bedrock_provider.py for Arkon
             │ • Enable Bedrock model access (1-2 days)
             │
Weeks 9-10   │ One-time migration
             │ • Run tools/confluence-migration for 2-3 Confluence spaces
             │ • Brain Owner reviews compilation plans
             │ • Verify wiki output in Arkon portal
             │
Weeks 11-13  │ Auto-ingestion
             │ • GitLab CI post-deploy webhook → Arkon ingest endpoint
             │ • AI opens MRs against the vault repo (NO auto-merge)
             │ • Brain Owner approves first MRs — tune prompts
             │
Weeks 14-16  │ Scale + MCP rollout
             │ • Expand auto-ingest to 5 systems
             │ • Issue MCP tokens to 30-50 engineers
             │ • Adoption + conflict dashboards
             │
Weeks 17-18  │ Hardening + handoff
             │ • Brain Owner SOP
             │ • Operations runbook
             │ • Decision: roll out bank-wide?
```

### 4.5 MVP 2 cost

| Item | Calculation | $ |
|---|---|---|
| Senior engineer | $2,500/mo × 3 months | ~$7,500 |
| AI API (Bedrock, 3 months) | ~$100/mo × 3 | ~$300 |
| AWS infra (Lambda/ECS, RDS, OpenSearch) | ~$150/mo × 3 | ~$450 |
| Buffer | | ~$750 |
| **MVP 2 total** | | **~$9K** |

**MVP 1 + MVP 2 combined**: ~$12K over 4-5 months.

### 4.6 MVP 2 success criteria

- ✅ **Code merge → docs auto-updated via MR within 24h**
- ✅ **≥80% of AI-generated MRs** approved by Brain Owner without major edits
- ✅ **≥30 engineers** using Arkon MCP/Kiro weekly
- ✅ **2-3 Confluence spaces** migrated, content reconciled
- ✅ CloudTrail + Git audit trail passes a compliance review

---

## 5. Cumulative 3-year ROI

Assumptions: 50 devs, $12/h, 15 hires/year, 4 audits/year, 10 major incidents/year.

| Savings category | $/year |
|---|---|
| Faster onboarding (15 hires × 23 days × 8h × $12) | $33,120 |
| Reduced search/research (30 devs × 4h × 50 weeks × $12) | $72,000 |
| Faster audit prep | $13,440 |
| Incident MTTR -15% | $7,500 |
| Senior departure insurance | $10,000 |
| **Total (conservative)** | **~$136K/year** |

**3-year cumulative**:

| Year | Cost | Savings | Net | Cumulative |
|---|---|---|---|---|
| Year 1 (MVP 1 + MVP 2 + 50% ramp) | $12K + $14K ops = $26K | $68K | +$42K | +$42K |
| Year 2 (steady state) | $14K | $136K | +$122K | +$164K |
| Year 3 (maturity) | $14K | $180K | +$166K | +$330K |
| **3-year total** | **$54K** | **$384K** | | **Net +$330K (~6×)** |

---

## 6. Risk Management

| Risk | Severity | Mitigation |
|---|---|---|
| MVP 1 fails to drive adoption | 🟡 Medium | Pilot one squad, hard gate at week 6, ready to stop |
| AI hallucinations | 🔴 High | Mandatory citations, MR review, audit log |
| Customer data leakage via AI | 🟢 Low | Bedrock in-VPC, no egress, Anthropic doesn't train |
| Vault becomes a doc graveyard | 🟡 Medium | MVP 1 builds the habit first; MVP 2 layers automation on top |
| AI cost overruns | 🟢 Low | Sonnet vs Haiku per task, batch ingest, threshold alerts |

---

## 7. Decision Requested

### Approve now (MVP 1)

1. **Phase 1 — MVP 1 Foundation** (6 weeks, ~$3K opportunity cost, only ~$600 fresh cash for Kiro license)
2. **Brain Owner**: nominate one Tech Lead to be Brain Owner, allocate 25% of their time
3. **Pilot system**: pick 1-2 systems with the worst docs and low blast radius
4. **Hard gate at week 6**: review against the 5 success criteria, decide whether to commit to MVP 2

### Conditional approval (MVP 2)

5. Approval contingent on MVP 1 results. If we pass the gate → kick off MVP 2:
   - Enable AWS Bedrock model access (1-2 days)
   - Allocate 1 senior × 3 months
   - Budget ~$9K (Bedrock + AWS infra + buffer)

### Open questions

1. **Brain Owner candidate**: who will own the Brain Owner role for MVP 1?
2. **Pilot system**: which system would leadership choose?
3. **AWS region**: `ap-southeast-1` (Singapore) or another for Bedrock?
4. **Confluence scope**: which spaces should MVP 2 migrate first?

---

*This proposal is built on Karpathy's "LLM Wiki" pattern and the open-source Arkon codebase, adapted for a banking context where compliance, auditability, and human-in-the-loop oversight are top priorities.*
