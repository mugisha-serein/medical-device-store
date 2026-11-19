from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.brute_force import BruteForceProtector, LockedException
from app.core.config import get_settings
from app.core.database import get_db
from app.core.rate_limit import RateLimiter
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
)
from app.identity.models import User
from app.identity.schemas import (
    UserCreate,
    UserResponse,
    TokenResponse,
    LoginRequest,
    RefreshRequest,
    PasswordChangeRequest,
)

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["Auth"])
protector = BruteForceProtector()


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimiter(settings.RATE_LIMIT_REGISTER))],
)
async def register(data: UserCreate, db: AsyncSession = Depends(get_db)):
    # Check duplicate email
    result = await db.execute(select(User).where(User.email == data.email.lower()))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        email=data.email.lower(),
        name=data.name.strip(),
        password_hash=hash_password(data.password),
    )
    db.add(user)
    await db.flush()

    access_token = create_access_token(data={"sub": user.id, "is_admin": user.is_admin})
    refresh_token = create_refresh_token(data={"sub": user.id})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(RateLimiter(settings.RATE_LIMIT_LOGIN))],
)
async def login(data: LoginRequest, db: AsyncSession = Depends(get_db)):
    email = data.email.lower()

    # 1. Check brute-force lockout BEFORE querying the database
    try:
        await protector.check_locked(email)
    except LockedException as exc:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account temporarily locked due to too many failed attempts. "
                   f"Try again in {exc.retry_after} seconds.",
            headers={"Retry-After": str(exc.retry_after)},
        )

    # 2. Verify credentials
    result = await db.execute(
        select(User).where(User.email == email, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.password_hash):
        # 3a. Record failure — may trigger lockout
        status_info = await protector.record_failure(email)
        remaining = status_info["remaining"]
        if status_info["locked"]:
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail=f"Account locked after {protector.max_failures} failed attempts. "
                       f"Try again in {protector.lockout_seconds} seconds.",
                headers={"Retry-After": str(protector.lockout_seconds)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Incorrect email or password. "
                   f"{remaining} attempt(s) remaining before lockout.",
        )

    # 3b. Success — clear failure history
    await protector.record_success(email)

    access_token = create_access_token(data={"sub": user.id, "is_admin": user.is_admin})
    refresh_token = create_refresh_token(data={"sub": user.id})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = decode_token(data.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type.",
        )

    user_id = payload.get("sub")
    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )

    access_token = create_access_token(data={"sub": user.id, "is_admin": user.is_admin})
    refresh_token = create_refresh_token(data={"sub": user.id})

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user=UserResponse.model_validate(user),
    )





@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    data: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    current_user.password_hash = hash_password(data.new_password)
    db.add(current_user)


# ---- Brute-force management endpoints (admin only) ----

class LockoutUnlockRequest(BaseModel):
    email: EmailStr


class LockoutStatusResponse(BaseModel):
    email: str
    locked: bool
    lockout_remaining_seconds: int
    failures_in_window: int
    max_failures: int


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return current_user


@router.post("/lockout/unlock", response_model=LockoutStatusResponse)
async def unlock_account(
    data: LockoutUnlockRequest,
    _admin: User = Depends(require_admin),
):
    """Admin endpoint: manually unlock a brute-force-locked account."""
    status_info = await protector.unlock(data.email)
    return LockoutStatusResponse(**status_info)


@router.get("/lockout/status/{email}", response_model=LockoutStatusResponse)
async def lockout_status(
    email: str,
    _admin: User = Depends(require_admin),
):
    """Admin endpoint: check lockout status for an email."""
    status_info = await protector.get_status(email)
    return LockoutStatusResponse(**status_info)
