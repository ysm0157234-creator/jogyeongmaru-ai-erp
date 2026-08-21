from __future__ import annotations

from app.services.document_manager import build_documents
from app.services.drive_manager import collect_drive_assets
from app.services.image_manager import image_from_selection
from app.services.package_manager import build_manifest, build_package
from app.services.service_errors import RequiredFileMissingError

# Backward-compatible export: older routers import this exception from workflow.py.
__all__ = ["RequiredFileMissingError", "run_workflow"]


def run_workflow(variety_name: str, draft_data: dict) -> tuple[bytes, dict]:
    """Create the complete report package without failing on optional assets."""
    assets = collect_drive_assets(variety_name, draft_data)
    warnings = list(assets.warnings)

    overall_image = image_from_selection(draft_data, "overall", warnings)
    closeup_image = image_from_selection(draft_data, "closeup", warnings)

    documents = build_documents(
        draft_data=draft_data,
        shipment=assets.shipment,
        quarantine_number=str(draft_data.get("quarantine_number") or "").strip()
        or assets.quarantine_number,
        overall_image=overall_image,
        closeup_image=closeup_image,
        warnings=warnings,
        invoice_name=assets.invoice_name,
        quarantine_name=assets.quarantine_name,
    )

    manifest = build_manifest(variety_name, draft_data, assets, documents, warnings)
    package = build_package(
        variety_name=variety_name,
        assets=assets,
        documents=documents,
        overall_image=overall_image,
        closeup_image=closeup_image,
        manifest=manifest,
    )
    return package, manifest
