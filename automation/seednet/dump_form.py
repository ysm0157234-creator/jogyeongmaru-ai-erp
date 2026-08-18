"""1단계: 신고 작성 화면의 입력 항목 구조를 파일로 뽑아낸다.

신고 폼은 로그인 안쪽이라 미리 볼 수 없다. 추측으로 선택자를 짜면 틀리므로,
먼저 실제 화면 구조를 뽑아서 그것을 보고 입력 매핑(field_map.json)을 만든다.

    python -m seednet.dump_form
"""

from __future__ import annotations

import json
from pathlib import Path

from seednet import config
from seednet.browser import close_session, open_session

OUTPUT = Path("automation/form_dump.json")

_EXTRACT = """
() => {
  const label = (el) => {
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) return l.innerText.trim();
    }
    const wrap = el.closest('label');
    if (wrap) return wrap.innerText.trim();
    const cell = el.closest('td');
    if (cell) {
      const row = cell.closest('tr');
      const th = row && row.querySelector('th');
      if (th) return th.innerText.trim();
    }
    return '';
  };
  const nodes = [...document.querySelectorAll('input,select,textarea,button,a.btn')];
  return {
    url: location.href,
    title: document.title,
    headings: [...document.querySelectorAll('h1,h2,h3,legend,caption')]
      .map(h => h.innerText.trim()).filter(Boolean).slice(0, 40),
    controls: nodes.map(el => ({
      tag: el.tagName.toLowerCase(),
      type: el.type || '',
      name: el.name || '',
      id: el.id || '',
      label: label(el),
      text: (el.innerText || el.value || '').trim().slice(0, 40),
      options: el.tagName === 'SELECT'
        ? [...el.options].map(o => ({ value: o.value, text: o.text.trim() })).slice(0, 30)
        : undefined,
      required: el.required || false,
      hidden: el.type === 'hidden' || !el.offsetParent,
    })),
  };
}
"""


def main() -> None:
    playwright, browser, context, page = open_session()
    try:
        page.goto(config.REPORT_LIST_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)

        print("=" * 62)
        print("  신고 '작성/신규신청' 화면까지 직접 이동해 주세요.")
        print("  작성 폼이 화면에 보이면 이 터미널에서 Enter를 누르세요.")
        print("=" * 62)
        input("\n준비되면 Enter > ")

        dump = page.evaluate(_EXTRACT)
        # 프레임을 쓰는 화면이면 프레임 안쪽도 같이 담는다.
        dump["frames"] = []
        for frame in page.frames[1:]:
            try:
                dump["frames"].append(frame.evaluate(_EXTRACT))
            except Exception as exc:
                dump["frames"].append({"error": str(exc), "url": frame.url})

        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8")

        visible = [c for c in dump["controls"] if not c["hidden"]]
        print(f"\n저장: {OUTPUT}")
        print(f"입력 항목 {len(dump['controls'])}개 (보이는 것 {len(visible)}개), 프레임 {len(dump['frames'])}개")
        for control in visible[:30]:
            print(f"  {control['tag']:<8} {control['type']:<10} name={control['name']:<24} {control['label'][:26]}")
    finally:
        close_session(playwright, browser, context, keep_open=True)
        print("\n브라우저는 열어둡니다. 확인 후 직접 닫으세요.")


if __name__ == "__main__":
    main()
