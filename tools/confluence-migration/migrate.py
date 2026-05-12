"""
Confluence → Arkon one-time migration CLI.

Pulls every page in a Confluence space, converts to Markdown, and uploads
to Arkon as a Source so the MRP pipeline compiles them into the wiki.

Idempotent: state.json maps Confluence page_id → Arkon source_id, so re-running
the command skips already-migrated pages. Safe to interrupt and resume.

Usage:
    python migrate.py --space ENG --knowledge-type-slug tech-decisions
    python migrate.py --space ENG --kt tech-decisions --limit 5 --dry-run

Required env vars (.env or shell):
    CONFLUENCE_URL          e.g. https://acme.atlassian.net/wiki
    CONFLUENCE_USERNAME     atlassian account email
    CONFLUENCE_API_TOKEN    api token from id.atlassian.com
    ARKON_URL               e.g. http://localhost:8000
    ARKON_EMAIL             arkon admin email
    ARKON_PASSWORD          arkon admin password
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import httpx
from atlassian import Confluence
from dotenv import load_dotenv
from markdownify import markdownify as md
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

console = Console()
logger = logging.getLogger("confluence-migrate")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    confluence_url: str
    confluence_username: str
    confluence_api_token: str
    arkon_url: str
    arkon_email: str
    arkon_password: str

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv()
        required = [
            "CONFLUENCE_URL", "CONFLUENCE_USERNAME", "CONFLUENCE_API_TOKEN",
            "ARKON_URL", "ARKON_EMAIL", "ARKON_PASSWORD",
        ]
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            console.print(f"[red]Missing env vars: {', '.join(missing)}[/red]")
            console.print("Copy .env.example to .env and fill in values.")
            sys.exit(1)
        return cls(
            confluence_url=os.environ["CONFLUENCE_URL"].rstrip("/"),
            confluence_username=os.environ["CONFLUENCE_USERNAME"],
            confluence_api_token=os.environ["CONFLUENCE_API_TOKEN"],
            arkon_url=os.environ["ARKON_URL"].rstrip("/"),
            arkon_email=os.environ["ARKON_EMAIL"],
            arkon_password=os.environ["ARKON_PASSWORD"],
        )


# ---------------------------------------------------------------------------
# Arkon client
# ---------------------------------------------------------------------------

class ArkonClient:
    """Thin Arkon REST client. Logs in once, reuses JWT."""

    def __init__(self, base_url: str, email: str, password: str):
        self._base = base_url
        self._email = email
        self._password = password
        self._token: str | None = None
        self._client = httpx.Client(timeout=60)

    def login(self) -> None:
        resp = self._client.post(
            f"{self._base}/api/auth/login",
            json={"email": self._email, "password": self._password},
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        logger.info("Arkon login successful")

    @property
    def _headers(self) -> dict[str, str]:
        if not self._token:
            raise RuntimeError("Not logged in — call login() first")
        return {"Authorization": f"Bearer {self._token}"}

    def get_knowledge_type_id(self, slug: str) -> str:
        resp = self._client.get(
            f"{self._base}/api/knowledge-types",
            headers=self._headers,
        )
        resp.raise_for_status()
        for kt in resp.json():
            if kt.get("slug") == slug:
                return kt["id"]
        raise ValueError(
            f"Knowledge type '{slug}' not found in Arkon. "
            f"Create it first in Admin Portal → Knowledge Types."
        )

    def upload_markdown(
        self,
        title: str,
        markdown: str,
        knowledge_type_id: str,
    ) -> str:
        """Upload markdown as a Source. Returns source_id."""
        safe_name = "".join(c if c.isalnum() or c in "-_." else "_" for c in title)[:120]
        filename = f"{safe_name}.md"
        files = {"file": (filename, markdown.encode("utf-8"), "text/markdown")}
        data = {"title": title, "knowledge_type_id": knowledge_type_id}
        resp = self._client.post(
            f"{self._base}/api/sources/upload",
            headers=self._headers,
            files=files,
            data=data,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def close(self) -> None:
        self._client.close()


# ---------------------------------------------------------------------------
# Confluence helpers
# ---------------------------------------------------------------------------

def iter_pages(conf: Confluence, space_key: str, batch: int = 50) -> Iterator[dict]:
    """Yield every page in a space, paginating through the API."""
    start = 0
    while True:
        pages = conf.get_all_pages_from_space(
            space=space_key,
            start=start,
            limit=batch,
            expand="body.storage,version,ancestors",
            status="current",
        )
        if not pages:
            return
        yield from pages
        if len(pages) < batch:
            return
        start += batch


def page_to_markdown(page: dict, confluence_base: str) -> str:
    """Convert a Confluence page (storage format) to Markdown with provenance header."""
    title = page.get("title", "Untitled")
    page_id = page["id"]
    storage_html = page.get("body", {}).get("storage", {}).get("value", "")
    page_url = f"{confluence_base}/spaces/_/pages/{page_id}"

    body_md = md(storage_html, heading_style="ATX").strip()
    header = (
        f"# {title}\n\n"
        f"> **Source:** Confluence page · [{title}]({page_url}) · "
        f"page_id `{page_id}` · version {page.get('version', {}).get('number', '?')}\n\n"
        "---\n\n"
    )
    return header + body_md + "\n"


# ---------------------------------------------------------------------------
# State (idempotency)
# ---------------------------------------------------------------------------

class State:
    """Tracks confluence_page_id → arkon_source_id so reruns skip done pages."""

    def __init__(self, path: Path):
        self.path = path
        self.mapping: dict[str, str] = {}
        if path.exists():
            self.mapping = json.loads(path.read_text())

    def is_done(self, page_id: str) -> bool:
        return page_id in self.mapping

    def mark_done(self, page_id: str, source_id: str) -> None:
        self.mapping[page_id] = source_id
        self.path.write_text(json.dumps(self.mapping, indent=2))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Migrate Confluence space → Arkon")
    p.add_argument("--space", required=True, help="Confluence space key (e.g. ENG)")
    p.add_argument(
        "--knowledge-type-slug", "--kt",
        dest="kt_slug",
        required=True,
        help="Arkon knowledge type slug (must already exist in Arkon)",
    )
    p.add_argument("--limit", type=int, default=None, help="Max pages to migrate (omit = all)")
    p.add_argument("--dry-run", action="store_true", help="Fetch + convert but don't upload")
    p.add_argument("--state", default="state.json", help="State file for idempotency")
    p.add_argument("--report", default="report.csv", help="CSV report of migrated pages")
    p.add_argument("--sleep", type=float, default=0.5, help="Sleep between uploads (rate limit)")
    return p.parse_args()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = parse_args()
    cfg = Config.from_env()

    console.print(f"[bold]Confluence → Arkon migration[/bold]")
    console.print(f"  space            = [cyan]{args.space}[/cyan]")
    console.print(f"  knowledge type   = [cyan]{args.kt_slug}[/cyan]")
    console.print(f"  dry run          = {args.dry_run}")
    console.print(f"  limit            = {args.limit or 'all'}")
    console.print()

    # 1. Confluence client
    conf = Confluence(
        url=cfg.confluence_url,
        username=cfg.confluence_username,
        password=cfg.confluence_api_token,
        cloud=True,
    )

    # 2. Arkon client + resolve KT
    arkon = ArkonClient(cfg.arkon_url, cfg.arkon_email, cfg.arkon_password)
    arkon.login()
    kt_id = arkon.get_knowledge_type_id(args.kt_slug)
    console.print(f"  resolved kt_id   = {kt_id}")
    console.print()

    # 3. State + report
    state = State(Path(args.state))
    report_path = Path(args.report)
    report_new = not report_path.exists()
    report_fh = report_path.open("a", newline="", encoding="utf-8")
    report = csv.writer(report_fh)
    if report_new:
        report.writerow(["confluence_page_id", "title", "arkon_source_id", "status", "error"])

    # 4. Iterate pages
    stats = {"migrated": 0, "skipped": 0, "errors": 0}
    started = time.time()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed} pages"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"Migrating space {args.space}...", total=None)

        for i, page in enumerate(iter_pages(conf, args.space)):
            if args.limit and i >= args.limit:
                break

            page_id = page["id"]
            title = page.get("title", "Untitled")

            if state.is_done(page_id):
                stats["skipped"] += 1
                progress.advance(task)
                continue

            try:
                markdown = page_to_markdown(page, cfg.confluence_url)

                if args.dry_run:
                    source_id = f"DRY_RUN_{page_id}"
                else:
                    source_id = arkon.upload_markdown(title, markdown, kt_id)
                    state.mark_done(page_id, source_id)
                    time.sleep(args.sleep)

                stats["migrated"] += 1
                report.writerow([page_id, title, source_id, "ok", ""])
                report_fh.flush()
                progress.advance(task)

            except httpx.HTTPStatusError as e:
                stats["errors"] += 1
                err = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
                logger.error(f"Failed page {page_id} '{title}': {err}")
                report.writerow([page_id, title, "", "error", err])
                report_fh.flush()
                progress.advance(task)
            except Exception as e:  # noqa: BLE001 — log + continue, don't break the batch
                stats["errors"] += 1
                logger.exception(f"Failed page {page_id} '{title}'")
                report.writerow([page_id, title, "", "error", str(e)[:200]])
                report_fh.flush()
                progress.advance(task)

    report_fh.close()
    arkon.close()

    elapsed = time.time() - started
    console.print()
    console.print(f"[bold green]Done in {elapsed:.1f}s[/bold green]")
    console.print(f"  migrated  = {stats['migrated']}")
    console.print(f"  skipped   = {stats['skipped']} (already in state)")
    console.print(f"  errors    = {stats['errors']}")
    console.print(f"  state     → {args.state}")
    console.print(f"  report    → {args.report}")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
