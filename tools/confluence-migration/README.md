# Confluence → Arkon migration

One-time CLI tool to bulk-migrate every page in a Confluence space into Arkon.
The script fetches Confluence pages, converts them to Markdown, and uploads
them as Sources so the **MRP pipeline** compiles them into the Wiki.

## What it does

```
┌──────────────┐    REST API     ┌──────────────┐    REST API     ┌──────────────┐
│  Confluence  │ ──────────────► │  migrate.py  │ ──────────────► │    Arkon     │
│  (existing)  │  list+fetch     │   (this CLI) │  upload .md     │  /api/sources│
└──────────────┘                 └──────────────┘                 └──────┬───────┘
                                                                         │
                                                                         ▼
                                                              MRP pipeline → Wiki
```

- ✅ **Idempotent** — re-running skips pages already migrated (tracked in `state.json`)
- ✅ **Resumable** — safe to Ctrl+C and re-run
- ✅ **Dry-run mode** — preview without writing
- ✅ **CSV report** of every page migrated, including failures
- ✅ **Provenance header** — every Markdown file links back to the original Confluence page
- ✅ **Rate-limited** — configurable sleep between uploads

## Quick start

```bash
# 1. Install deps (venv recommended)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env
# edit .env with your Confluence + Arkon credentials

# 3. Prerequisite: create the knowledge type in Arkon admin portal
#    e.g. slug=tech-decisions, name="Tech Decisions"

# 4. Dry-run first (no writes)
python migrate.py --space ENG --kt tech-decisions --limit 3 --dry-run

# 5. Real run
python migrate.py --space ENG --kt tech-decisions
```

## CLI flags

| Flag | Required | Default | Description |
|---|---|---|---|
| `--space` | yes | — | Confluence space key (e.g. `ENG`) |
| `--knowledge-type-slug` / `--kt` | yes | — | Arkon knowledge type slug (must already exist) |
| `--limit N` | no | all | Stop after N pages — useful for testing |
| `--dry-run` | no | false | Convert pages but skip upload |
| `--state PATH` | no | `state.json` | Mapping `confluence_page_id → arkon_source_id` for idempotency |
| `--report PATH` | no | `report.csv` | Per-page status report |
| `--sleep SECONDS` | no | `0.5` | Sleep between uploads (avoid rate limits) |

## Output

- `state.json` — `{"<confluence_page_id>": "<arkon_source_id>", ...}`. Re-runs read this to skip done pages. **Keep it** between runs.
- `report.csv` — `confluence_page_id,title,arkon_source_id,status,error`. Append-only — every run appends new rows.

## Markdown shape uploaded to Arkon

Every page gets a provenance header so the MRP pipeline can cite back to Confluence:

```markdown
# Original page title

> **Source:** Confluence page · [Original page title](https://acme.atlassian.net/wiki/spaces/_/pages/12345) · page_id `12345` · version 7

---

[converted markdown body...]
```

This means every wiki claim compiled by MRP traces back to the exact Confluence
page — auditors get a clean chain of custody.

## Common operations

### Migrate one specific space, small batch first

```bash
python migrate.py --space DEV --kt engineering --limit 5 --dry-run
# Review report.csv, then:
python migrate.py --space DEV --kt engineering --limit 5
# Verify in Arkon admin portal, then full run:
python migrate.py --space DEV --kt engineering
```

### Migrate multiple spaces

Just rerun with different `--space` values. The same `state.json` is fine —
Confluence page IDs are globally unique across spaces.

```bash
python migrate.py --space ENG --kt engineering
python migrate.py --space PROD --kt product-decisions
python migrate.py --space OPS --kt runbooks
```

### Retry only the failed pages

After a run, failures are logged in `report.csv` with `status=error`. They
are **not** added to `state.json` so a plain rerun retries them automatically.
For a clean retry, delete the error rows from the CSV first.

### Throttling

If you hit Confluence or Arkon rate limits:

```bash
python migrate.py --space ENG --kt engineering --sleep 2
```

## Architecture notes

- Auth flow: script logs into Arkon at startup with email/password → JWT → all
  uploads use `Authorization: Bearer <jwt>`. Token expiry hasn't been an issue
  for typical batch sizes (<1000 pages, <1 hour). For very large migrations,
  re-login periodically in `iter_pages`.

- The script uses `body.storage` (Confluence's internal XHTML format) and runs
  it through `markdownify`. This handles most Confluence elements well
  (headings, lists, tables, code blocks, links). Macros like `{toc}`,
  `{include}`, `{jira}` are rendered as inert HTML — Arkon's MRP pipeline
  ignores them gracefully.

- Attachments are **not** migrated by this script (yet). If you need them, add
  a `get_attachments_from_content(page_id)` loop and call Arkon's
  `/api/sources/upload` per attachment file. Open a follow-up if you need this.

- Pages are migrated **flat** — Confluence hierarchy (parent/child page tree)
  is not preserved as Arkon source hierarchy. Arkon's MRP pipeline builds its
  own knowledge graph from content, so this isn't a loss — but if you want the
  hierarchy as metadata, add `ancestors` parsing to `page_to_markdown()`.

## When to stop using this script

This is **one-time migration tooling**. For ongoing Confluence → Arkon sync,
build a proper integration (Confluence webhook → Arkon background job, or a
scheduled poller). This CLI is intentionally simple — don't grow it into a
sync daemon.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Missing env vars` | Copy `.env.example` → `.env`, fill values |
| `Knowledge type 'X' not found` | Create the knowledge type in Arkon admin portal first |
| `401 Unauthorized` on login | Wrong Arkon email/password — test via the portal first |
| `403 Forbidden` on upload | Arkon user lacks `doc:create` permission — promote in admin portal |
| `Confluence 401` | API token expired or username mismatch (must be email for Cloud) |
| `Confluence 429 too many requests` | Increase `--sleep` |
| HTML garbage in Markdown | Some Confluence macros don't convert cleanly. Review affected pages manually in Arkon. |
| Re-run uploads duplicate pages | You deleted `state.json` between runs — keep it. |
