"""브라우저를 띄우고 사람이 로그인할 때까지 기다린다.

아이디·비밀번호와 인증서는 **사람이 직접 입력한다.** 자동화가 대신 넣지 않는다.
로그인이 끝나면 세션을 저장해서 다음 실행 때는 기다리는 단계를 건너뛴다.
"""

from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from seednet import config


def _looks_logged_in(page: Page) -> bool:
    try:
        body = page.inner_text("body", timeout=3000)
    except Exception:
        return False
    return any(hint in body for hint in config.LOGGED_IN_HINTS)


def open_session(headless: bool = False):
    """브라우저를 열고 로그인된 페이지를 돌려준다. 호출한 쪽에서 close_session을 부른다."""
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=headless)

    state = Path(config.STORAGE_STATE)
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

    return playwright, browser, context, page


def close_session(playwright, browser, context, *, keep_open: bool = False) -> None:
    if keep_open:
        return
    context.close()
    browser.close()
    playwright.stop()
