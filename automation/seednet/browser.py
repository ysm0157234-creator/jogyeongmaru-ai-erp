"""브라우저를 띄우고 사람이 로그인할 때까지 기다린다.

아이디·비밀번호와 인증서는 **사람이 직접 입력한다.** 자동화가 대신 넣지 않는다.
로그인이 끝나면 세션을 저장해서 다음 실행 때는 기다리는 단계를 건너뛴다.

브라우저는 한 번 띄우면 계속 재사용한다. 사람이 [종자원 접수요청]을 눌러야 하므로
실행이 끝나도 닫지 않는데, 그렇다고 Playwright를 정리해 버리면 다음 실행이 시작조차
못 한다(같은 스레드에 asyncio 루프가 남아 "Sync API inside the asyncio loop" 오류가 난다).
그래서 정리하지 않고 그대로 들고 있다가 다음 요청에 다시 쓴다.
"""

from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from seednet import config

# 도우미가 살아 있는 동안 유지하는 하나뿐인 브라우저.
_session: dict | None = None


def _looks_logged_in(page: Page) -> bool:
    try:
        body = page.inner_text("body", timeout=3000)
    except Exception:
        return False
    return any(hint in body for hint in config.LOGGED_IN_HINTS)


def _alive(session: dict) -> bool:
    """브라우저가 아직 쓸 수 있는 상태인지 본다(사람이 닫았을 수 있다)."""
    try:
        return session["browser"].is_connected() and not session["page"].is_closed()
    except Exception:
        return False


def _discard(session: dict) -> None:
    for key in ("context", "browser"):
        try:
            session[key].close()
        except Exception:
            pass
    try:
        session["playwright"].stop()
    except Exception:
        pass


def open_session(headless: bool = False):
    """로그인된 페이지를 돌려준다. 이미 띄워둔 브라우저가 있으면 그것을 다시 쓴다."""
    global _session

    if _session is not None:
        if _alive(_session):
            page = _session["page"]
            try:
                page.bring_to_front()
            except Exception:
                pass
            return _session["playwright"], _session["browser"], _session["context"], page
        # 사람이 창을 닫았다면 흔적을 치우고 새로 띄운다.
        _discard(_session)
        _session = None

    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=headless)

    state = config.STORAGE_STATE
    context = browser.new_context(
        storage_state=str(state) if state.exists() else None,
        accept_downloads=True,
    )
    page = context.new_page()
    page.goto(config.REPORT_LIST_URL, wait_until="domcontentloaded")

    if not _looks_logged_in(page):
        page.goto(config.LOGIN_URL, wait_until="domcontentloaded")
        print("\n" + "=" * 62)
        print("  브라우저 창에서 직접 로그인해 주세요.")
        print("  (아이디/비밀번호 또는 공동인증서 — 자동화는 입력하지 않습니다)")
        print(f"  최대 {config.LOGIN_WAIT_SECONDS // 60}분까지 기다립니다.")
        print("=" * 62 + "\n")

        deadline = time.time() + config.LOGIN_WAIT_SECONDS
        while time.time() < deadline:
            if _looks_logged_in(page):
                break
            page.wait_for_timeout(2000)
        else:
            raise TimeoutError("로그인을 기다리다 시간이 지났습니다.")

        state.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(state))
        print(f"로그인 확인. 세션을 {state}에 저장했습니다.\n")

    _session = {"playwright": playwright, "browser": browser, "context": context, "page": page}
    return playwright, browser, context, page


def close_session(playwright, browser, context, *, keep_open: bool = False) -> None:
    """사람이 제출해야 하므로 기본적으로 닫지 않는다.

    Playwright도 정리하지 않는다. 정리하면 다음 실행이 같은 스레드에서 시작하지 못한다.
    """
    if keep_open:
        return

    global _session
    if _session is not None:
        _discard(_session)
        _session = None
