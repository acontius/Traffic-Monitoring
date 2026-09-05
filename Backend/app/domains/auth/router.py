"""Login, token refresh, and logout (SRS 3.1)."""

from fastapi import APIRouter, Depends, HTTPException, status

from Backend.app.core.security import CurrentUser, get_current_user
from Backend.app.db.pool import get_pool
from Backend.app.domains.auth import service
from Backend.app.domains.auth.schemas import LoginRequest, RefreshRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, pool=Depends(get_pool)):
    try:
        return await service.login(pool, body.username, body.password)
    except service.InvalidCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="نام کاربری یا رمز عبور نادرست است",
        ) from exc


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, pool=Depends(get_pool)):
    try:
        return await service.refresh(pool, body.refresh_token)
    except service.InvalidRefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        ) from exc


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: RefreshRequest,
    user: CurrentUser = Depends(get_current_user),
    pool=Depends(get_pool),
):
    await service.logout(pool, user.username, body.refresh_token)
