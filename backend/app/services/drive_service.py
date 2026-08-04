from __future__ import annotations

import io
import json
import socket
from dataclasses import dataclass

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from app.core.config import get_settings

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"
socket.setdefaulttimeout(35)


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    parents: list[str]
    web_view_link: str | None = None


class DriveNotConfiguredError(RuntimeError):
    pass


class DriveOperationError(RuntimeError):
    pass


class GoogleDriveService:
    def __init__(self):
        settings = get_settings()
        raw = settings.google_service_account_json.strip()

        missing = []
        if not raw:
            missing.append("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not settings.shipment_overview_file_id.strip():
            missing.append("SHIPMENT_OVERVIEW_FILE_ID")
        if not settings.import_2025_folder_id.strip():
            missing.append("IMPORT_2025_FOLDER_ID")

        if missing:
            raise DriveNotConfiguredError(
                "Render 환경변수가 누락되었습니다: " + ", ".join(missing)
            )

        try:
            info = json.loads(raw)
            credentials = service_account.Credentials.from_service_account_info(
                info,
                scopes=SCOPES,
            )
            self.client = build(
                "drive",
                "v3",
                credentials=credentials,
                cache_discovery=False,
            )
        except Exception as exc:
            raise DriveNotConfiguredError(
                f"Google Drive 인증에 실패했습니다: {exc}"
            ) from exc

    @staticmethod
    def _to_file(data: dict) -> DriveFile:
        return DriveFile(
            id=data["id"],
            name=data["name"],
            mime_type=data["mimeType"],
            parents=data.get("parents", []),
            web_view_link=data.get("webViewLink"),
        )

    @staticmethod
    def normalize(value: str) -> str:
        return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())

    @staticmethod
    def _escape_query(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'")

    def get_metadata(self, file_id: str) -> DriveFile:
        try:
            data = self.client.files().get(
                fileId=file_id,
                fields="id,name,mimeType,parents,webViewLink",
                supportsAllDrives=True,
            ).execute(num_retries=2)
            return self._to_file(data)
        except Exception as exc:
            raise DriveOperationError(f"Drive 파일 정보를 읽지 못했습니다: {exc}") from exc

    def list_children(
        self,
        folder_id: str,
        *,
        max_items: int = 1000,
    ) -> list[DriveFile]:
        result: list[DriveFile] = []
        page_token = None

        try:
            while len(result) < max_items:
                response = self.client.files().list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    fields="nextPageToken,files(id,name,mimeType,parents,webViewLink)",
                    pageSize=min(500, max_items - len(result)),
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                ).execute(num_retries=2)

                result.extend(
                    self._to_file(data)
                    for data in response.get("files", [])
                )
                page_token = response.get("nextPageToken")
                if not page_token:
                    break
            return result[:max_items]
        except Exception as exc:
            raise DriveOperationError(f"Drive 폴더 목록을 읽지 못했습니다: {exc}") from exc

    def find_child_folder(
        self,
        parent_folder_id: str,
        folder_name: str,
    ) -> DriveFile | None:
        wanted = self.normalize(folder_name)
        if not wanted:
            return None

        children = self.list_children(parent_folder_id)
        folders = [item for item in children if item.mime_type == FOLDER_MIME]

        exact = [item for item in folders if self.normalize(item.name) == wanted]
        if exact:
            return exact[0]

        partial = [
            item for item in folders
            if wanted in self.normalize(item.name)
            or self.normalize(item.name) in wanted
        ]
        return partial[0] if partial else None

    def walk(
        self,
        folder_id: str,
        *,
        max_depth: int = 3,
        max_items: int = 1500,
    ) -> list[DriveFile]:
        found: list[DriveFile] = []
        queue: list[tuple[str, int]] = [(folder_id, 0)]
        visited: set[str] = set()

        while queue and len(found) < max_items:
            current, depth = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            for item in self.list_children(current):
                found.append(item)
                if len(found) >= max_items:
                    break
                if item.mime_type == FOLDER_MIME and depth < max_depth:
                    queue.append((item.id, depth + 1))
        return found

    def search_files(
        self,
        text: str,
        *,
        name_only: bool = False,
        mime_types: list[str] | None = None,
        limit: int = 100,
    ) -> list[DriveFile]:
        clean = text.strip()
        if not clean:
            return []

        field = "name" if name_only else "fullText"
        query_parts = [
            f"{field} contains '{self._escape_query(clean)}'",
            "trashed = false",
        ]
        if mime_types:
            conditions = " or ".join(
                f"mimeType = '{self._escape_query(mime)}'"
                for mime in mime_types
            )
            query_parts.append(f"({conditions})")

        try:
            response = self.client.files().list(
                q=" and ".join(query_parts),
                fields="files(id,name,mimeType,parents,webViewLink)",
                pageSize=min(limit, 1000),
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute(num_retries=2)
            return [
                self._to_file(data)
                for data in response.get("files", [])
            ]
        except Exception as exc:
            raise DriveOperationError(f"Google Drive 검색에 실패했습니다: {exc}") from exc

    def download(
        self,
        file_id: str,
        *,
        max_chunks: int = 100,
    ) -> bytes:
        try:
            request = self.client.files().get_media(
                fileId=file_id,
                supportsAllDrives=True,
            )
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(
                buffer,
                request,
                chunksize=5 * 1024 * 1024,
            )

            done = False
            chunk_count = 0
            while not done:
                if chunk_count >= max_chunks:
                    raise DriveOperationError(
                        "Drive 파일 다운로드가 너무 오래 걸려 중단했습니다."
                    )
                _, done = downloader.next_chunk(num_retries=2)
                chunk_count += 1
            return buffer.getvalue()
        except DriveOperationError:
            raise
        except socket.timeout as exc:
            raise DriveOperationError(
                "Google Drive 응답 시간이 초과되었습니다."
            ) from exc
        except Exception as exc:
            raise DriveOperationError(
                f"Drive 파일 다운로드 중 오류가 발생했습니다: {exc}"
            ) from exc
