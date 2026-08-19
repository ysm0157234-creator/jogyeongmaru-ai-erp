"""맥에서 도는 작은 도우미 서버.

ERP 웹앱(Render)에서 신고 자동입력 버튼을 누르면 여기로 ZIP이 넘어온다.
자동화는 **로그인된 브라우저가 있는 이 컴퓨터에서** 돌아야 하므로 서버가 대신할 수 없다.

    python3 -m seednet.local_server

- 이 컴퓨터 안(127.0.0.1)에서만 받는다. 외부에서는 접근할 수 없다.
- 아이디·비밀번호는 다루지 않는다. 로그인은 처음 한 번 브라우저에서 직접 한다.
- [종자원 접수요청]은 누르지 않는다.
"""

from __future__ import annotations

import cgi
import json
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from seednet.runner import run

HOST = "127.0.0.1"
PORT = 8765

# 한 번에 하나만 돌린다. 브라우저를 공유하기 때문이다.
_lock = threading.Lock()


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
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"]},
            )
            item = form["file"]
            data = item.file.read()
        except Exception:
            self._send(400, {"error": "ZIP 파일을 받지 못했습니다."})
            return

        temp = Path(tempfile.mkdtemp(prefix="seednet-")) / "package.zip"
        temp.write_bytes(data)
        print(f"\n[요청] {temp.name} {len(data):,} bytes — 자동 입력을 시작합니다.")

        with _lock:
            try:
                result = run(temp, interactive=False)
            except Exception as exc:
                traceback.print_exc()
                self._send(500, {"error": f"{type(exc).__name__}: {exc}"})
                return

        print(f"[완료] 자동 {len(result['done'])}건 / 직접 {len(result['todo'])}건")
        self._send(200, result)

    def log_message(self, *args) -> None:
        return  # 접속 로그는 찍지 않는다.


def main() -> None:
    server = HTTPServer((HOST, PORT), Handler)
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
