"""
MCP Auth Service — token verification and scope resolution.

This service is called by the MCP server to:
1. Verify employee MCP token
2. Resolve the employee's department
3. Compute the effective knowledge scope (what docs they can access)
4. Generate and revoke tokens
"""

import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.models import Department, Employee, KnowledgeScope, Source


@dataclass
class ResolvedIdentity:
    """The authenticated employee context, passed to MCP tools."""
    employee_id: uuid.UUID
    employee_name: str
    department_id: uuid.UUID
    department_name: str
    allowed_knowledge_types: Optional[list[str]] = None  # None = all
    allowed_source_ids: Optional[list[str]] = None       # None = all
    is_admin: bool = False


class MCPAuthService:
    """Handles MCP token auth and knowledge scope resolution."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def verify_token(self, token: str) -> Optional[ResolvedIdentity]:
        """
        Verify an MCP bearer token and return the resolved identity.
        Returns None if token is invalid/inactive.
        """
        stmt = (
            select(Employee)
            .where(Employee.mcp_token == token, Employee.is_active == True)
            .options(selectinload(Employee.department))
        )
        result = await self.db.execute(stmt)
        employee = result.scalar_one_or_none()

        if not employee:
            return None

        # Update last_connected
        employee.last_connected = datetime.utcnow()
        await self.db.flush()

        # Resolve knowledge scope
        identity = await self._resolve_scope(employee)
        return identity

    async def _resolve_scope(self, employee: Employee) -> ResolvedIdentity:
        """
        Compute effective knowledge scope for an employee.

        Resolution order:
        1. Check personal scopes (employee_id-specific)
        2. Fall back to department scopes
        3. If no scopes defined → access all knowledge (open policy)
        """
        # 1. Personal scopes first
        stmt = select(KnowledgeScope).where(
            KnowledgeScope.employee_id == employee.id
        )
        result = await self.db.execute(stmt)
        personal_scopes = result.scalars().all()

        # 2. Department scopes
        stmt = select(KnowledgeScope).where(
            KnowledgeScope.department_id == employee.department_id,
            KnowledgeScope.employee_id == None,
        )
        result = await self.db.execute(stmt)
        dept_scopes = result.scalars().all()

        # Merge scopes: personal overrides department
        effective_scopes = personal_scopes if personal_scopes else dept_scopes

        if not effective_scopes:
            # No scopes defined → open access (default permissive)
            return ResolvedIdentity(
                employee_id=employee.id,
                employee_name=employee.name,
                department_id=employee.department_id,
                department_name=employee.department.name if employee.department else "",
            )

        # Collect grant types
        allowed_types: set[str] = set()
        allowed_sources: set[str] = set()
        has_type_filter = False
        has_source_filter = False

        for scope in effective_scopes:
            if scope.scope_type == "grant":
                if scope.knowledge_type_slugs:
                    has_type_filter = True
                    allowed_types.update(scope.knowledge_type_slugs)
                if scope.source_ids:
                    has_source_filter = True
                    allowed_sources.update(str(s) for s in scope.source_ids)

        return ResolvedIdentity(
            employee_id=employee.id,
            employee_name=employee.name,
            department_id=employee.department_id,
            department_name=employee.department.name if employee.department else "",
            allowed_knowledge_types=list(allowed_types) if has_type_filter else None,
            allowed_source_ids=list(allowed_sources) if has_source_filter else None,
        )

    # --- Token Management ---

    async def generate_token(self, employee_id: uuid.UUID) -> str:
        """Generate a new MCP token for an employee."""
        token = f"ark_{secrets.token_urlsafe(32)}"

        stmt = (
            update(Employee)
            .where(Employee.id == employee_id)
            .values(mcp_token=token)
        )
        await self.db.execute(stmt)
        await self.db.flush()

        logger.info(f"Generated MCP token for employee {employee_id}")
        return token

    async def revoke_token(self, employee_id: uuid.UUID) -> bool:
        """Revoke an employee's MCP token."""
        stmt = (
            update(Employee)
            .where(Employee.id == employee_id)
            .values(mcp_token=None)
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount > 0


def apply_scope_filter(query, identity: ResolvedIdentity):
    """
    Apply knowledge scope filters to a SQLAlchemy query on the Source table.

    Usage:
        stmt = select(Source).where(Source.status == "ready")
        stmt = apply_scope_filter(stmt, identity)
    """
    if identity.allowed_source_ids is not None:
        source_uuids = [uuid.UUID(s) for s in identity.allowed_source_ids]
        query = query.where(Source.id.in_(source_uuids))
    elif identity.allowed_knowledge_types is not None:
        # Resolve slugs to knowledge_type IDs via subquery
        from app.database.models import KnowledgeType
        from sqlalchemy import select as sa_select
        kt_subq = sa_select(KnowledgeType.id).where(
            KnowledgeType.slug.in_(identity.allowed_knowledge_types)
        )
        query = query.where(Source.knowledge_type_id.in_(kt_subq))
    return query
