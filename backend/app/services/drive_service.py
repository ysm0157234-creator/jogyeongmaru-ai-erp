
import io
import json
from dataclasses import dataclass
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.core.config import get_settings

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    parents: list[str]
    web_view_link: str | None = None

class DriveNotConfiguredError(RuntimeError):
    pass

class GoogleDriveService:
    def __init__(self):
        settings = get_settings()
        raw = settings.google_service_account_json.strip()
        if not raw:
            raise DriveNotConfiguredError(
                "GOOGLE_SERVICE_ACCOUNT_JSON이 설정되지 않았습니다."
            )
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DriveNotConfiguredError(
                "GOOGLE_SERVICE_ACCOUNT_JSON 형식이 올바르지 않습니다."
            ) from exc

        credentials = service_account.Credentials.from_service_account_info(
            info,
            scopes=SCOPES,
        )
        self.client = build("drive", "v3", credentials=credentials, cache_discovery=False)

    def get_metadata(self, file_id: str) -> DriveFile:
        data = self.client.files().get(
            fileId=file_id,
            fields="id,name,mimeType,parents,webViewLink",
            supportsAllDrives=True,
        ).execute()
        return DriveFile(
            id=data["id"],
            name=data["name"],
            mime_type=data["mimeType"],
            parents=data.get("parents", []),
            web_view_link=data.get("webViewLink"),
        )

    def list_children(self, folder_id: str) -> list[DriveFile]:
        result: list[DriveFile] = []
        page_token = None
        while True:
            response = self.client.files().list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken,files(id,name,mimeType,parents,webViewLink)",
                pageSize=1000,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute()
            for data in response.get("files", []):
                result.append(
                    DriveFile(
                        id=data["id"],
                        name=data["name"],
                        mime_type=data["mimeType"],
                        parents=data.get("parents", []),
                        web_view_link=data.get("webViewLink"),
                    )
                )
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return result

    def walk(self, folder_id: str, max_depth: int = 5) -> list[DriveFile]:
        found: list[DriveFile] = []
        queue: list[tuple[str, int]] = [(folder_id, 0)]
        while queue:
            current, depth = queue.pop(0)
            for item in self.list_children(current):
                found.append(item)
                if (
                    item.mime_type == "application/vnd.google-apps.folder"
                    and depth < max_depth
                ):
                    queue.append((item.id, depth + 1))
        return found

    def download(self, file_id: str) -> bytes:
        request = self.client.files().get_media(fileId=file_id, supportsAllDrives=True)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()
