from __future__ import annotations

import copy
import io
import traceback

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.text_utils import sanitize_postgres_text
from app.models.ai_draft import AIDraft
from app.models.user import User
from app.schemas.ai_draft import AIDraftResponse, AIDraftUpdateRequest, AIGenerateRequest, AIFileGenerateRequest
from app.services.drive_service import DriveNotConfiguredError, DriveOperationError
from app.services.gemini_service import GeminiError, GeminiNotConfiguredError
from app.services.google_search_service import GoogleSearchNotConfiguredError
from app.services.plant_research_service import PlantResearchError, research_variety
from app.services.service_errors import RequiredFileMissingError
from app.services.workflow import run_workflow
from app.services.upload_service import UploadError, get_upload, save_upload
from .deps import get_current_user

router = APIRouter(prefix="/api/ai-reports", tags=["ai-reports"])

BUILD_VERSION = "v20.1-actual-project-stable"


def get_owned_draft(db: Session, draft_id: int, user: User) -> AIDraft:
    draft = db.get(AIDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="AI 신고 초안을 찾을 수 없습니다.")
    if draft.created_by != user.id:
        raise HTTPException(status_code=403, detail="이 신고 초안에 접근할 권한이 없습니다.")
    return draft


def validate_result_data(data: dict) -> None:
    # 사진·Drive 첨부가 없어도 초안을 저장하고 호환용 DOCX를 생성할 수 있다.
    # 비어 있는 항목은 최종 ZIP의 경고와 자리표시자로 명확히 표시한다.
    if not isinstance(data, dict):
        raise HTTPException(status_code=422, detail="AI 초안 데이터 형식이 올바르지 않습니다.")


@router.get("/drive/status")
def drive_status(_: User = Depends(get_current_user)):
    from app.core.config import get_settings
    settings = get_settings()
    checks = {
        "GOOGLE_SERVICE_ACCOUNT_JSON": bool(settings.google_service_account_json.strip()),
        "SHIPMENT_OVERVIEW_FILE_ID": bool(settings.shipment_overview_file_id.strip()),
        "IMPORT_2025_FOLDER_ID": bool(settings.import_2025_folder_id.strip()),
        "IMPORT_2024_FOLDER_ID": bool(settings.import_2024_folder_id.strip()),
        "IMPORT_2023_FOLDER_ID": bool(settings.import_2023_folder_id.strip()),
        "SERPER_API_KEY": bool(settings.serper_api_key.strip()),
        "GEMINI_API_KEY": bool(settings.gemini_api_key.strip()),
    }
    required_keys = (
        "GOOGLE_SERVICE_ACCOUNT_JSON",
        "SHIPMENT_OVERVIEW_FILE_ID",
        "IMPORT_2025_FOLDER_ID",
        "IMPORT_2024_FOLDER_ID",
        "IMPORT_2023_FOLDER_ID",
        "SERPER_API_KEY",
        "GEMINI_API_KEY",
    )
    missing = [
        key
        for key in required_keys
        if not checks[key]
    ]
    return {
        "configured": all(
            checks[key]
            for key in (
                "GOOGLE_SERVICE_ACCOUNT_JSON",
                "SHIPMENT_OVERVIEW_FILE_ID",
                "IMPORT_2025_FOLDER_ID",
                "IMPORT_2024_FOLDER_ID",
                "IMPORT_2023_FOLDER_ID",
                "SERPER_API_KEY",
                "GEMINI_API_KEY",
            )
        ),
        "drive_configured": all(
            checks[key]
            for key in (
                "GOOGLE_SERVICE_ACCOUNT_JSON",
                "SHIPMENT_OVERVIEW_FILE_ID",
                "IMPORT_2025_FOLDER_ID",
                "IMPORT_2024_FOLDER_ID",
                "IMPORT_2023_FOLDER_ID",
            )
        ),
        "research_configured": all(
            checks[key]
            for key in (
                "SERPER_API_KEY",
            )
        ),
        "gemini_configured": checks["GEMINI_API_KEY"],
        "missing_environment_variables": missing,
        "build_version": BUILD_VERSION,
        "message": (
            (
                f"Google Drive·Serper·Gemini·HWPX 연결 완료 ({BUILD_VERSION})"
            )
            if not missing
            else "누락된 Render 환경변수: " + ", ".join(missing)
        ),
    }


def _run_research_job(draft_id: int, variety_name: str, agency: str) -> None:
    """긴 인터넷 조사를 요청 응답과 분리해서 실행한다."""
    db = SessionLocal()
    try:
        draft = db.get(AIDraft, draft_id)
        if not draft:
            print(f"[AI JOB] draft not found: {draft_id}", flush=True)
            return

        draft.status = "조사 중"
        draft.result_data = {
            "build_version": BUILD_VERSION,
            "research_query": variety_name,
            "progress": "Serper 검색과 AI 번역·요약을 진행하고 있습니다.",
        }
        db.add(draft)
        db.commit()

        result = research_variety(variety_name, agency)
        if str(result.get("research_query", "")).strip().lower() != variety_name.lower():
            raise PlantResearchError(
                "조사 결과의 품종 식별자가 현재 입력값과 일치하지 않습니다."
            )

        result["build_version"] = BUILD_VERSION
        result.pop("progress", None)

        draft = db.get(AIDraft, draft_id)
        if not draft:
            return
        draft.result_data = sanitize_postgres_text(result)
        draft.status = "검토 대기"
        db.add(draft)
        db.commit()
        print(f"[AI JOB SUCCESS] draft={draft_id} variety={variety_name}", flush=True)

    except Exception as error:
        traceback.print_exc()
        db.rollback()
        try:
            draft = db.get(AIDraft, draft_id)
            if draft:
                draft.status = "생성 실패"
                draft.result_data = {
                    "build_version": BUILD_VERSION,
                    "research_query": variety_name,
                    "error": f"{type(error).__name__}: {error}",
                }
                db.add(draft)
                db.commit()
        except Exception:
            traceback.print_exc()
            db.rollback()
    finally:
        db.close()




@router.post("/upload")
async def upload_supporting_file(
    role: str = Form(...),
    file: UploadFile = File(...),
    _: User = Depends(get_current_user),
):
    allowed = {"overall", "closeup", "invoice", "quarantine"}
    if role not in allowed:
        raise HTTPException(status_code=422, detail="지원하지 않는 업로드 종류입니다.")
    try:
        data = await file.read()
        stored = save_upload(
            data=data,
            filename=file.filename or "upload.bin",
            content_type=file.content_type or "application/octet-stream",
            role=role,
        )
    except UploadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "upload_id": stored.id,
        "role": role,
        "name": stored.original_name,
        "content_type": stored.content_type,
        "preview_url": f"/api/ai-reports/uploads/{stored.id}",
    }


@router.get("/uploads/{upload_id}")
def read_uploaded_file(upload_id: str):
    try:
        stored = get_upload(upload_id)
    except UploadError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        stored.path,
        media_type=stored.content_type,
        filename=stored.original_name,
    )


@router.post("/generate", response_model=AIDraftResponse, status_code=201)
def generate_ai_report(
    payload: AIGenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    variety_name = payload.variety_name.strip()
    if not variety_name:
        raise HTTPException(status_code=422, detail="신고할 품종명을 입력하세요.")

    # 먼저 빈 작업 레코드를 저장하고 즉시 응답한다. 긴 조사는 응답 후 실행된다.
    draft = AIDraft(
        query_name=variety_name,
        agency=payload.agency,
        status="대기 중",
        result_data={
            "build_version": BUILD_VERSION,
            "research_query": variety_name,
            "progress": "조사 작업을 준비하고 있습니다.",
        },
        created_by=current_user.id,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)

    background_tasks.add_task(
        _run_research_job,
        draft.id,
        variety_name,
        payload.agency,
    )
    return draft


@router.put("/{draft_id}", response_model=AIDraftResponse)
def update_ai_draft(draft_id: int, payload: AIDraftUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    draft = get_owned_draft(db, draft_id, current_user)
    validate_result_data(payload.result_data)
    draft.result_data = sanitize_postgres_text(copy.deepcopy(payload.result_data))
    draft.status = payload.status or "검토 완료"
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@router.get("", response_model=list[AIDraftResponse])
def list_ai_drafts(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(AIDraft).filter(AIDraft.created_by == current_user.id).order_by(AIDraft.id.desc()).all()


@router.post("/generate-files")
def generate_files(payload: AIFileGenerateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    draft = get_owned_draft(db, payload.draft_id, current_user)
    validate_result_data(draft.result_data)
    variety_name = payload.variety_name.strip() or draft.query_name
    try:
        zip_bytes, manifest = run_workflow(variety_name, copy.deepcopy(draft.result_data))
        if not zip_bytes:
            raise RuntimeError("생성된 ZIP 데이터가 비어 있습니다.")
        print("[ZIP SUCCESS]", {"draft_id": draft.id, "variety": variety_name, "shipment": manifest.get("shipment"), "size": len(zip_bytes)}, flush=True)
    except DriveNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except DriveOperationError as error:
        raise HTTPException(status_code=502, detail=f"Google Drive 처리 오류: {error}") from error
    except RequiredFileMissingError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"완성 패키지 생성 중 오류: {type(error).__name__}: {error}") from error

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="production_sales_report_complete.zip"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/{draft_id}", response_model=AIDraftResponse)
def get_ai_draft(draft_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return get_owned_draft(db, draft_id, current_user)
