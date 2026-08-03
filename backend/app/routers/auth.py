from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserResponse
from .deps import get_current_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


def authenticate_user(
    email: str,
    password: str,
    db: Session,
) -> User:
    user = db.query(User).filter(User.email == email).first()

    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# ERP 웹사이트 로그인용: JSON 방식
@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    user = authenticate_user(
        email=payload.email,
        password=payload.password,
        db=db,
    )

    return TokenResponse(
        access_token=create_access_token(user.email),
    )


# Swagger Authorize 전용: form 방식
@router.post("/token", response_model=TokenResponse)
def swagger_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = authenticate_user(
        email=form_data.username,
        password=form_data.password,
        db=db,
    )

    return TokenResponse(
        access_token=create_access_token(user.email),
    )


@router.get("/me", response_model=UserResponse)
def me(
    current_user: User = Depends(get_current_user),
):
    return current_user
