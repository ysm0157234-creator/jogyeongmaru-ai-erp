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

# Google API 통신이 무한정 기다리지 않도록 제한
socket.setdefaulttimeout(30)


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

        try:
            credentials = (
                service_account.Credentials.from_service_account_info(
                    info,
                    scopes=SCOPES,
                )
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
    def _to_drive_file(data: dict) -> DriveFile:
        return DriveFile(
            id=data["id"],
            name=data["name"],
            mime_type=data["mimeType"],
            parents=data.get("parents", []),
            web_view_link=data.get("webViewLink"),
        )

    @staticmethod
    def _escape_query(value: str) -> str:
        return (
            value
            .replace("\\", "\\\\")
            .replace("'", "\\'")
        )

    def get_metadata(self, file_id: str) -> DriveFile:
        try:
            data = (
                self.client.files()
                .get(
                    fileId=file_id,
                    fields=(
                        "id,name,mimeType,"
                        "parents,webViewLink"
                    ),
                    supportsAllDrives=True,
                )
                .execute(num_retries=2)
            )

            return self._to_drive_file(data)

        except HttpError as exc:
            raise DriveOperationError(
                f"Drive 파일 정보를 읽지 못했습니다: {exc}"
            ) from exc

        except Exception as exc:
            raise DriveOperationError(
                f"Drive 파일 정보 조회 중 오류가 발생했습니다: {exc}"
            ) from exc

    def list_children(
        self,
        folder_id: str,
        max_items: int = 500,
    ) -> list[DriveFile]:
        """
        특정 폴더의 바로 아래 항목만 조회한다.

        max_items를 두어 파일이 너무 많은 폴더에서
        무한정 페이지를 읽지 않도록 제한한다.
        """

        result: list[DriveFile] = []
        page_token = None

        try:
            while len(result) < max_items:
                response = (
                    self.client.files()
                    .list(
                        q=(
                            f"'{folder_id}' in parents "
                            "and trashed = false"
                        ),
                        fields=(
                            "nextPageToken,"
                            "files("
                            "id,name,mimeType,"
                            "parents,webViewLink"
                            ")"
                        ),
                        pageSize=min(200, max_items),
                        pageToken=page_token,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                    )
                    .execute(num_retries=2)
                )

                for data in response.get("files", []):
                    result.append(
                        self._to_drive_file(data)
                    )

                    if len(result) >= max_items:
                        break

                page_token = response.get("nextPageToken")

                if not page_token:
                    break

            return result

        except HttpError as exc:
            raise DriveOperationError(
                f"Drive 폴더 목록을 읽지 못했습니다: {exc}"
            ) from exc

        except Exception as exc:
            raise DriveOperationError(
                f"Drive 폴더 검색 중 오류가 발생했습니다: {exc}"
            ) from exc

    def walk(
        self,
        folder_id: str,
        max_depth: int = 3,
        max_folders: int = 100,
        max_items: int = 2000,
    ) -> list[DriveFile]:
        """
        하위 폴더를 제한적으로 탐색한다.

        전체 Drive를 끝없이 순회하지 않도록:
        - 깊이 제한
        - 폴더 수 제한
        - 전체 항목 수 제한
        """

        found: list[DriveFile] = []
        queue: list[tuple[str, int]] = [
            (folder_id, 0)
        ]
        visited_folders: set[str] = set()

        while queue:
            current_folder_id, depth = queue.pop(0)

            if current_folder_id in visited_folders:
                continue

            visited_folders.add(current_folder_id)

            if len(visited_folders) > max_folders:
                break

            children = self.list_children(
                current_folder_id,
                max_items=500,
            )

            for item in children:
                found.append(item)

                if len(found) >= max_items:
                    return found

                if (
                    item.mime_type
                    == "application/vnd.google-apps.folder"
                    and depth < max_depth
                ):
                    queue.append(
                        (item.id, depth + 1)
                    )

        return found

    def search_files(
        self,
        text: str,
        *,
        name_only: bool = False,
        mime_types: list[str] | None = None,
        limit: int = 100,
    ) -> list[DriveFile]:
        """
        Google Drive 서버 검색을 사용한다.

        전체 폴더를 직접 순회하는 것보다 빠르다.

        name_only=False:
            파일명과 Google이 색인한 문서 내용을 검색

        name_only=True:
            파일명만 검색
        """

        text = text.strip()

        if not text:
            return []

        escaped = self._escape_query(text)

        field = "name" if name_only else "fullText"

        query_parts = [
            f"{field} contains '{escaped}'",
            "trashed = false",
        ]

        if mime_types:
            mime_query = " or ".join(
                (
                    "mimeType = "
                    f"'{self._escape_query(mime)}'"
                )
                for mime in mime_types
            )

            query_parts.append(
                f"({mime_query})"
            )

        try:
            response = (
                self.client.files()
                .list(
                    q=" and ".join(query_parts),
                    fields=(
                        "files("
                        "id,name,mimeType,"
                        "parents,webViewLink"
                        ")"
                    ),
                    pageSize=min(limit, 1000),
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute(num_retries=2)
            )

            return [
                self._to_drive_file(data)
                for data in response.get("files", [])
            ]

        except HttpError as exc:
            raise DriveOperationError(
                f"Google Drive 검색에 실패했습니다: {exc}"
            ) from exc

        except Exception as exc:
            raise DriveOperationError(
                f"Google Drive 검색 중 오류가 발생했습니다: {exc}"
            ) from exc

    def search_filename_terms(
        self,
        terms: list[str],
        *,
        limit_each: int = 50,
    ) -> list[DriveFile]:
        """
        여러 검색어로 파일명을 검색하고
        중복 파일은 한 번만 반환한다.
        """

        unique: dict[str, DriveFile] = {}

        for term in terms:
            clean_term = term.strip()

            if not clean_term:
                continue

            results = self.search_files(
                clean_term,
                name_only=True,
                limit=limit_each,
            )

            for item in results:
                unique[item.id] = item

        return list(unique.values())

    def download(
        self,
        file_id: str,
        max_chunks: int = 100,
    ) -> bytes:
        """
        Drive 파일을 다운로드한다.

        max_chunks를 두어 다운로드가 끝없이
        반복되는 상황을 막는다.
        """

        try:
            request = self.client.files().get_media(
                fileId=file_id,
                supportsAllDrives=True,
            )

            buffer = io.BytesIO()

            downloader = MediaIoBaseDownload(
                buffer,
                request,
                chunksize=1024 * 1024 * 5,
            )

            done = False
            chunk_count = 0

            while not done:
                if chunk_count >= max_chunks:
                    raise DriveOperationError(
                        "Drive 파일 다운로드가 너무 오래 걸려 중단했습니다."
                    )

                _, done = downloader.next_chunk(
                    num_retries=2
                )

                chunk_count += 1

            return buffer.getvalue()

        except DriveOperationError:
            raise

        except HttpError as exc:
            raise DriveOperationError(
                f"Drive 파일 다운로드에 실패했습니다: {exc}"
            ) from exc

        except socket.timeout as exc:
            raise DriveOperationError(
                "Google Drive 응답시간이 초과되었습니다."
            ) from exc

        except Exception as exc:
            raise DriveOperationError(
                f"Drive 파일 다운로드 중 오류가 발생했습니다: {exc}"
            ) from exc
