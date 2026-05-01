"""
Auth router — login, logout, profile, change password.

Two roles:
  - admin: Full access to admin portal (settings, RBAC, KB management)
  - employee: View scoped knowledge, get MCP token for Claude Desktop
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.database.models import Employee
from app.services.auth_service import (
    authenticate_employee,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ProfileResponse(BaseModel):
    id: str
    name: str
    email: str
    role: str
    department_id: str
    department_name: str
    is_active: bool
    has_mcp_token: bool


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """
    Authenticate with email + password. Returns JWT token.
    Works for both admin and employee roles.
    """
    employee = await authenticate_employee(db, req.email, req.password)
    if not employee:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(
        employee_id=str(employee.id),
        role=employee.role,
        name=employee.name,
    )

    return LoginResponse(
        access_token=token,
        user={
            "id": str(employee.id),
            "name": employee.name,
            "email": employee.email,
            "role": employee.role,
            "department_id": str(employee.department_id),
            "department_name": employee.department.name if employee.department else "",
        },
    )


@router.get("/auth/me", response_model=ProfileResponse)
async def get_profile(current_user: Employee = Depends(get_current_user)):
    """Get current user profile. Validates the JWT is still valid."""
    return ProfileResponse(
        id=str(current_user.id),
        name=current_user.name,
        email=current_user.email,
        role=current_user.role,
        department_id=str(current_user.department_id),
        department_name=current_user.department.name if current_user.department else "",
        is_active=current_user.is_active,
        has_mcp_token=bool(current_user.mcp_token),
    )


@router.post("/auth/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: Employee = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Change the current user's password."""
    if not current_user.password_hash:
        raise HTTPException(400, "No password set. Contact admin.")

    if not verify_password(req.current_password, current_user.password_hash):
        raise HTTPException(401, "Current password is incorrect")

    if len(req.new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters")

    current_user.password_hash = hash_password(req.new_password)
    await db.flush()
    return {"message": "Password changed successfully"}


@router.get("/auth/status")
async def auth_status():
    """Check if auth is required (public endpoint for frontend)."""
    return {"auth_required": True}
