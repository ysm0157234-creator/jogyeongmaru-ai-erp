from __future__ import annotations

import mimetypes
import re
import uuid
from dataclasses import dataclass
from pathlib import Path


UPLOAD_ROOT = Path('/tmp/jm_ai_uploads')
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


class UploadError(RuntimeError):
    pass


@dataclass
class StoredUpload:
    id: str
    path: Path
    original_name: str
    content_type: str
    role: str


def _safe_suffix(filename: str, content_type: str) -> str:
    suffix = Path(filename or '').suffix.lower()
    if re.fullmatch(r'\.[a-z0-9]{1,8}', suffix):
        return suffix
    guessed = mimetypes.guess_extension(content_type or '') or '.bin'
    return guessed


def save_upload(*, data: bytes, filename: str, content_type: str, role: str) -> StoredUpload:
    if not data:
        raise UploadError('업로드 파일이 비어 있습니다.')
    if len(data) > 25 * 1024 * 1024:
        raise UploadError('파일은 25MB 이하만 업로드할 수 있습니다.')
    upload_id = uuid.uuid4().hex
    suffix = _safe_suffix(filename, content_type)
    path = UPLOAD_ROOT / f'{upload_id}{suffix}'
    path.write_bytes(data)
    meta = UPLOAD_ROOT / f'{upload_id}.meta'
    meta.write_text('\n'.join([role, filename or path.name, content_type or 'application/octet-stream', path.name]), encoding='utf-8')
    return StoredUpload(upload_id, path, filename or path.name, content_type or 'application/octet-stream', role)


def get_upload(upload_id: str) -> StoredUpload:
    if not re.fullmatch(r'[a-f0-9]{32}', upload_id or ''):
        raise UploadError('잘못된 업로드 ID입니다.')
    meta = UPLOAD_ROOT / f'{upload_id}.meta'
    if not meta.exists():
        raise UploadError('업로드 파일을 찾을 수 없습니다. Render 재시작 후에는 다시 업로드해야 합니다.')
    lines = meta.read_text(encoding='utf-8').splitlines()
    if len(lines) < 4:
        raise UploadError('업로드 메타정보가 손상되었습니다.')
    role, original_name, content_type, stored_name = lines[:4]
    path = UPLOAD_ROOT / stored_name
    if not path.exists():
        raise UploadError('업로드 파일이 만료되었거나 삭제되었습니다.')
    return StoredUpload(upload_id, path, original_name, content_type, role)
