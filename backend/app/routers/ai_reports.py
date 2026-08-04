from __future__ import annotations

import copy
import io
import traceback

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.ai_draft import AIDraft
from app.models.user import User
from app.schemas.ai_draft import AIDraftResponse, AIDraftUpdateRequest, AIGenerateRequest, AIFileGenerateRequest
from app.services.drive_service import DriveNotConfiguredError, DriveOperationError
from app.services.gemini_service import GeminiError, GeminiNotConfiguredError
from app.services.google_search_service import GoogleSearchNotConfiguredError
from app.services.plant_research_service import PlantResearchError, research_variety
from app.services.workflow import RequiredFileMissingError, run_workflow
from .deps import get_current_user

router = APIRouter(prefix="/api/ai-reports", tags=["ai-reports"])

BUILD_VERSION = "v9.0-strict-dynamic-variety"


def get_owned_draft(db: Session, draft_id: int, user: User) -> AIDraft:
    draft = db.get(AIDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="AI 신고 초안을 찾을 수 없습니다.")
    if draft.created_by != user.id:
        raise HTTPException(status_code=403, detail="이 신고 초안에 접근할 권한이 없습니다.")
    return draft


def validate_result_data(data: dict) -> None:
    selected = data.get("selected_images", {})
    if not selected.get("overall") or not selected.get("closeup"):
        raise HTTPException(status_code=422, detail="전체 모습과 꽃 근접 사진을 각각 선택해야 합니다.")
    if selected.get("overall") == selected.get("closeup"):
        raise HTTPException(status_code=422, detail="전체 모습과 꽃 근접 사진은 서로 달라야 합니다.")
    if not str(data.get("characteristics_draft", "")).strip():
        raise HTTPException(status_code=422, detail="품종 특성 설명이 비어 있습니다.")
    if not str(data.get("breeding_process_draft", "")).strip():
        raise HTTPException(status_code=422, detail="품종 육성과정이 비어 있습니다.")


@router.get("/drive/status")
def drive_status(_: User = Depends(get_current_user)):
    from app.core.config import get_settings
    settings = get_settings()
    checks = {
        "GOOGLE_SERVICE_ACCOUNT_JSON": bool(settings.google_service_account_json.strip()),
        "SHIPMENT_OVERVIEW_FILE_ID": bool(settings.shipment_overview_file_id.strip()),
        "IMPORT_2025_FOLDER_ID": bool(settings.import_2025_folder_id.strip()),
        "GOOGLE_SEARCH_API_KEY": bool(settings.google_search_api_key.strip()),
        "GOOGLE_SEARCH_ENGINE_ID": bool(settings.google_search_engine_id.strip()),
        "GEMINI_API_KEY": bool(settings.gemini_api_key.strip()),
    }
    missing = [key for key, ok in checks.items() if not ok]
    return {
        "configured": not missing,
        "drive_configured": all(checks[key] for key in ("GOOGLE_SERVICE_ACCOUNT_JSON", "SHIPMENT_OVERVIEW_FILE_ID", "IMPORT_2025_FOLDER_ID")),
        "research_configured": all(checks[key] for key in ("GOOGLE_SEARCH_API_KEY", "GOOGLE_SEARCH_ENGINE_ID", "GEMINI_API_KEY")),
        "missing_environment_variables": missing,
        "build_version": BUILD_VERSION,
        "message": (
            f"Google Drive·검색·Gemini 연결 준비 완료 ({BUILD_VERSION})"
            if not missing
            else "누락된 Render 환경변수: " + ", ".join(missing)
        ),
    }


@router.post("/generate", response_model=AIDraftResponse, status_code=201)
def generate_ai_report(payload: AIGenerateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    variety_name = payload.variety_name.strip()
    if not variety_name:
        raise HTTPException(status_code=422, detail="신고할 품종명을 입력하세요.")
    try:
        result = research_variety(variety_name, payload.agency)
        if str(result.get("research_query", "")).strip().lower() != variety_name.lower():
            raise PlantResearchError(
                "조사 결과의 품종 식별자가 현재 입력값과 일치하지 않습니다."
            )
        result["build_version"] = BUILD_VERSION
    except (GoogleSearchNotConfiguredError, GeminiNotConfiguredError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except (GeminiError, PlantResearchError) as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"품종 인터넷 조사 중 오류: {type(error).__name__}: {error}") from error

    draft = AIDraft(query_name=variety_name, agency=payload.agency, status="검토 대기", result_data=result, created_by=current_user.id)
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


@router.put("/{draft_id}", response_model=AIDraftResponse)
def update_ai_draft(draft_id: int, payload: AIDraftUpdateRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    draft = get_owned_draft(db, draft_id, current_user)
    validate_result_data(payload.result_data)
    draft.result_data = copy.deepcopy(payload.result_data)
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
