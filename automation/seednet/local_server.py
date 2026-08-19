"""맥에서 도는 작은 도우미 서버.

ERP 웹앱(Render)에서 신고 자동입력 버튼을 누르면 여기로 ZIP이 넘어온다.
자동화는 **로그인된 브라우저가 있는 이 컴퓨터에서** 돌아야 하므로 서버가 대신할 수 없다.

    python3 -m seednet.local_server

- 이 컴퓨터 안(127.0.0.1)에서만 받는다. 외부에서는 접근할 수 없다.
- 아이디·비밀번호는 다루지 않는다. 로그인은 처음 한 번 브라우저에서 직접 한다.
- [종자원 접수요청]은 누르지 않는다.
"""

from __future__ import annotations

import json
import re
import time
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from seednet import config
from seednet.runner import run

HOST = "127.0.0.1"
PORT = 8765

# 한 번에 하나만 돌린다. 브라우저를 공유하기 때문이다.
_lock = threading.Lock()


def parse_uploaded_file(content_type: str, body: bytes) -> bytes | None:
    """multipart 본문에서 file 부분만 꺼낸다.

    표준 라이브러리 cgi 모듈은 파이썬 3.13에서 없어졌다. 직원 PC마다 파이썬
    버전이 다를 수 있으므로 파일 하나 꺼내는 정도는 직접 처리한다.
    """
    if "boundary=" not in content_type:
        return None

    boundary = content_type.split("boundary=", 1)[1].strip().strip('"')
    marker = b"--" + boundary.encode()

    for part in body.split(marker):
        head, sep, data = part.partition(b"\r\n\r\n")
        if not sep or b'name="file"' not in head:
            continue
        # 각 부분 끝의 개행과 종료 표시를 걷어낸다.
        return data.rsplit(b"\r\n", 1)[0] if data.endswith(b"\r\n") else data.rstrip(b"\r\n-")

    return None


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send(200, {"ok": True})

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/health"):
            self._send(200, {"ok": True, "busy": _lock.locked()})
        else:
            self._send(404, {"error": "없는 주소입니다."})

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/run"):
            self._send(404, {"error": "없는 주소입니다."})
            return

        if _lock.locked():
            self._send(409, {"error": "이미 신고 자동입력이 실행 중입니다."})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            data = parse_uploaded_file(self.headers.get("Content-Type", ""), body)
        except Exception:
            data = None

        if not data:
            self._send(400, {"error": "ZIP 파일을 받지 못했습니다."})
            return

        stamp = time.strftime("%Y%m%d_%H%M%S")
        folder = config.ARCHIVE_DIR / stamp
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / "package.zip"
        temp.write_bytes(data)
        print(f"\n[요청] {len(data):,} bytes 받음 — 보관: {folder}")

        with _lock:
            try:
                result = run(temp, interactive=False)
            except Exception as exc:
                detail = traceback.format_exc()
                print(detail, flush=True)
                try:
                    (config.AUTOMATION_DIR / "last_run.log").open("a", encoding="utf-8").write(
                        "\n\n=== 실행 중 오류 ===\n" + detail
                    )
                except Exception:
                    pass
                self._send(500, {"error": f"{type(exc).__name__}: {exc}"})
                return

        # 품종명을 알게 됐으니 폴더 이름에 붙여 나중에 찾기 쉽게 한다.
        variety = re.sub(r'[\\/:*?"<>|]+', "_", str(result.get("variety") or "")).strip()
        if variety:
            renamed = config.ARCHIVE_DIR / f"{stamp}_{variety}"
            try:
                folder.rename(renamed)
                result["saved_to"] = str(renamed)
            except Exception:
                result["saved_to"] = str(folder)
        else:
            result["saved_to"] = str(folder)

        print(f"[완료] 자동 {len(result['done'])}건 / 직접 {len(result['todo'])}건")
        print(f"       자료 보관: {result['saved_to']}")
        self._send(200, result)

    def log_message(self, *args) -> None:
        return  # 접속 로그는 찍지 않는다.


class ReusableServer(HTTPServer):
    # 껐다 켤 때 포트가 잠깐 묶여 있어도 바로 다시 뜨게 한다.
    allow_reuse_address = True


def main() -> None:
    try:
        server = ReusableServer((HOST, PORT), Handler)
    except OSError as exc:
        if exc.errno == 48:  # Address already in use
            print("=" * 66)
            print("  도우미가 이미 실행 중입니다. 새로 띄우지 않아도 됩니다.")
            print("  (다른 터미널 창을 확인하세요. 그대로 두고 웹앱 버튼을 누르면 됩니다.)")
            print("=" * 66)
            return
        raise
    print("=" * 66)
    print(f"  국립종자원 신고 도우미 — http://{HOST}:{PORT}")
    print("  ERP 웹앱에서 [국립종자원 신고 자동입력] 버튼을 누르면 여기로 옵니다.")
    print("  이 창을 켜 두세요. 종료는 Ctrl+C.")
    print("=" * 66)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")


if __name__ == "__main__":
    main()
