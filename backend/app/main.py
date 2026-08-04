from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import Base, SessionLocal, engine
from app.core.security import hash_password
from app.models import User
from app.routers import auth, reports, ai_reports

settings = get_settings()

def seed_admin() -> None:
    db: Session = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == settings.admin_email).first()
        if not existing:
            existing = User(
                email=settings.admin_email,
                name="관리자",
                password_hash=hash_password(settings.admin_password),
            )
            db.add(existing)
        else:
            existing.password_hash = hash_password(settings.admin_password)
        db.commit()
    finally:
        db.close()

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    seed_admin()
    yield

app = FastAPI(
    title=settings.app_name,
    version="1.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=settings.cors_origin_list != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(reports.router)
app.include_router(ai_reports.router)

@app.get("/")
def root():
    return {"name": settings.app_name, "version": "1.2.0"}

@app.get("/health")
def health():
    return {"status": "ok"}
