from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from backend.core.security import create_access_token, hash_password, verify_password, TokenData
from backend.models.organization import Organization
from backend.models.user import User
from backend.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from backend.api.dependencies import DbSession

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: DbSession):
    # Check email uniqueness
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    org = Organization(
        name=payload.org_name,
        country_code=payload.org_country_code.upper(),
    )
    db.add(org)
    await db.flush()  # get org.id without committing

    user = User(
        org_id=org.id,
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role="admin",  # First user in an org is always admin
    )
    db.add(user)
    await db.flush()

    token = create_access_token(
        TokenData(user_id=user.id, org_id=org.id, email=user.email, role=user.role)
    )
    return TokenResponse(access_token=token, user_id=user.id, org_id=org.id, role=user.role)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: DbSession):
    user = await db.scalar(select(User).where(User.email == payload.email, User.is_active == True))
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(
        TokenData(user_id=user.id, org_id=user.org_id, email=user.email, role=user.role)
    )
    return TokenResponse(access_token=token, user_id=user.id, org_id=user.org_id, role=user.role)
