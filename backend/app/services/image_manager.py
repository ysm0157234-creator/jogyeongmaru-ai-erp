from __future__ import annotations

import io
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

from app.services.service_errors import RequiredFileMissingError
from app.services.upload_service import UploadError, get_upload


def selected_candidate(data: dict, role: str) -> dict | None:
    selected_id = (data.get("selected_images") or {}).get(role)
    if not selected_id:
        return None
    for item in data.get("image_candidates") or []:
        if item.get("id") == selected_id:
            return item
    return None


def candidate_urls(candidate: dict) -> list[str]:
    output: list[str] = []
    for key in ("download_url", "preview_url", "backup_url", "backup_url_2", "image_url"):
        value = str(candidate.get(key) or "").strip()
        if value and value not in output:
            output.append(value)
    return output


def normalize_image_to_jpeg(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            if image.mode in ("RGBA", "LA"):
                background = Image.new("RGB", image.size, "white")
                alpha = image.getchannel("A")
                background.paste(image.convert("RGB"), mask=alpha)
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")

            # Extremely large images can exhaust memory in document generation.
            image.thumbnail((3000, 3000), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=92, optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise RequiredFileMissingError(f"지원되지 않거나 손상된 이미지입니다: {exc}") from exc


def download_image(urls: list[str]) -> bytes:
    errors: list[str] = []
    for raw_url in urls:
        url = str(raw_url or "").strip()
        if not url:
            continue
        request = Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/142 Safari/537.36",
                "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*",
                "Referer": url,
            },
        )
        try:
            with urlopen(request, timeout=25) as response:
                content_type = str(response.headers.get("Content-Type", "")).lower()
                data = response.read(15_000_000)
                if not data:
                    raise ValueError("빈 이미지 응답")
                if "text/html" in content_type:
                    raise ValueError("이미지 대신 HTML 응답")
                return normalize_image_to_jpeg(data)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RequiredFileMissingError) as exc:
            errors.append(f"{url}: {exc}")

    detail = " / ".join(errors[-3:]) or "사용 가능한 이미지 URL 없음"
    raise RequiredFileMissingError(f"선택한 이미지를 내려받지 못했습니다: {detail}")


def placeholder_image(title: str, subtitle: str) -> bytes:
    image = Image.new("RGB", (1600, 1000), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((25, 25, 1575, 975), outline="gray", width=4)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 56)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
    except Exception:
        font = ImageFont.load_default()
        small = ImageFont.load_default()
    draw.text((100, 380), title, fill="black", font=font)
    draw.text((100, 480), subtitle, fill="gray", font=small)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()


def image_from_selection(draft_data: dict, role: str, warnings: list[str]) -> bytes:
    candidate = selected_candidate(draft_data, role)
    label = "전체 모습" if role == "overall" else "근접"
    if candidate:
        upload_id = str(candidate.get("upload_id") or "").strip()
        if upload_id:
            try:
                return normalize_image_to_jpeg(get_upload(upload_id).path.read_bytes())
            except (UploadError, OSError, RequiredFileMissingError) as exc:
                warnings.append(f"{label} 직접 업로드 사진을 읽지 못해 자리표시자를 사용했습니다: {exc}")
        urls = candidate_urls(candidate)
        if urls:
            try:
                return download_image(urls)
            except RequiredFileMissingError as exc:
                warnings.append(f"{label} 인터넷 사진 다운로드 실패로 자리표시자를 사용했습니다: {exc}")
    warnings.append(f"{label} 사진이 없어 직접 업로드가 필요합니다.")
    return placeholder_image(f"{label} 사진 미첨부", "사이트에서 사진을 직접 선택하거나 업로드하세요.")
