"""
브라우저 테스트 스크립트
1단계: 네이버 수동 로그인 → 쿠키 저장
2단계: 글쓰기 페이지 이동 → 셀렉터 검사
3단계: 자동 포스팅 테스트

사용법:
  python3 test_browser.py login
  python3 test_browser.py inspect <블로그아이디>
  python3 test_browser.py post <블로그아이디>
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from playwright.async_api import async_playwright

PROFILE_DIR = str(Path(__file__).parent / "storage" / "chrome_profiles" / "default")
Path(PROFILE_DIR).mkdir(parents=True, exist_ok=True)

STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-infobars",
]

STEALTH_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    window.chrome = {runtime: {}};
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    Object.defineProperty(navigator, 'languages', {get: () => ['ko-KR', 'ko', 'en-US', 'en']});
"""


async def step1_login():
    """1단계: 네이버 로그인 (수동) — 로그인 감지 시 자동 종료"""
    print("\n" + "=" * 60)
    print("  [1단계] 네이버 로그인")
    print("=" * 60)
    print("  브라우저가 열리면 네이버에 직접 로그인하세요.")
    print("  로그인이 감지되면 자동으로 쿠키를 저장하고 종료합니다.")
    print("  (최대 3분 대기)")
    print("=" * 60 + "\n")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            args=STEALTH_ARGS,
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            ignore_default_args=["--enable-automation"],
        )
        await context.add_init_script(STEALTH_SCRIPT)

        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://nid.naver.com/nidlogin.login")

        # 로그인 감지 대기 (최대 3분)
        print("  로그인 대기 중...")
        for i in range(180):
            await asyncio.sleep(1)
            url = page.url
            # 로그인 성공 시 리다이렉트됨
            if "nidlogin" not in url and "naver.com" in url:
                print(f"  ✓ 로그인 감지! ({url})")
                break
            if (i + 1) % 30 == 0:
                print(f"    ... {i + 1}초 경과, 계속 대기 중")
        else:
            print("  ⚠ 3분 타임아웃. 로그인되지 않았을 수 있습니다.")

        # naver.com으로 이동하여 쿠키 확인
        await page.goto("https://www.naver.com")
        await asyncio.sleep(2)
        print(f"  현재 URL: {page.url}")
        print("  ✓ 쿠키가 저장되었습니다. 다음 실행부터 자동 로그인됩니다.\n")

        await context.close()


async def _ensure_blog_write_access(page, context, blog_id: str) -> bool:
    """글쓰기 페이지 접근. 자동 로그인 후 직접 에디터로 재이동."""
    write_url = f"https://blog.naver.com/{blog_id}?Redirect=Write"

    # 1차: 글쓰기 URL 접속
    print(f"  [접속] → {write_url}")
    await page.goto(write_url, wait_until="domcontentloaded")
    await asyncio.sleep(3)

    # 이미 에디터에 도착한 경우
    if "nidlogin" not in page.url and "login" not in page.url.lower():
        print(f"  [접속] ✓ 바로 에디터 접속: {page.url[:80]}")
        return True

    # 로그인 페이지 → 자동 로그인 완료 대기 (쿠키로 자동 로그인될 수 있음)
    print("  [접속] 로그인 페이지 감지. 자동 로그인 대기 중...")
    for i in range(30):
        await asyncio.sleep(1)
        if "nidlogin" not in page.url and "login" not in page.url.lower():
            print(f"  [접속] ✓ 자동 로그인 성공: {page.url[:80]}")
            break
    else:
        # 자동 로그인 안 됨 → 수동 로그인 요청
        print("  [접속] 자동 로그인 안 됨. 브라우저에서 직접 로그인하세요. (최대 3분)")
        for i in range(180):
            await asyncio.sleep(1)
            if "nidlogin" not in page.url and "login" not in page.url.lower():
                print(f"  [접속] ✓ 수동 로그인 감지!")
                break
            if (i + 1) % 30 == 0:
                print(f"    ... {i + 1}초 경과")
        else:
            print("  [접속] ⚠ 타임아웃.")
            return False

    await asyncio.sleep(3)

    # 로그인 후 현재 위치 확인
    current = page.url
    print(f"  [접속] 로그인 후 위치: {current[:80]}")

    # 에디터가 아닌 곳(블로그 메인 등)으로 갔으면 → 에디터로 재이동
    editor_keywords = ["write", "editor", "postwrite", "SmartEditor"]
    if not any(kw.lower() in current.lower() for kw in editor_keywords):
        print("  [접속] 에디터가 아님 → 글쓰기 URL로 재이동...")

        # 여러 URL 형식 시도
        for url in [
            f"https://blog.naver.com/{blog_id}?Redirect=Write",
            f"https://blog.naver.com/{blog_id}/postwrite",
        ]:
            await page.goto(url, wait_until="domcontentloaded")
            await asyncio.sleep(5)

            # 새 탭이 열렸는지 확인
            pages = context.pages
            if len(pages) > 1:
                # 마지막 탭이 에디터일 수 있음
                last_page = pages[-1]
                if last_page != page:
                    print(f"  [접속] 새 탭 감지: {last_page.url[:80]}")
                    return True

            if "nidlogin" not in page.url and "login" not in page.url.lower():
                # 블로그 메인이 아닌 다른 곳에 도착했는지 확인
                print(f"  [접속] 이동 결과: {page.url[:80]}")

                # iframe 내부에 에디터가 있는지 확인
                for frame in page.frames:
                    frame_url = frame.url.lower()
                    if any(kw in frame_url for kw in ["write", "editor", "smarteditor"]):
                        print(f"  [접속] ✓ 에디터 iframe 발견: {frame.url[:80]}")
                        return True

                # URL이 바뀌었으면 성공으로 간주
                if page.url != current:
                    return True

        # 최종: 블로그 메인에서 글쓰기 버튼 클릭
        print("  [접속] 블로그 메인에서 글쓰기 버튼 클릭 시도...")
        await page.goto(f"https://blog.naver.com/{blog_id}", wait_until="domcontentloaded")
        await asyncio.sleep(3)

        for frame in page.frames:
            try:
                btn = await frame.query_selector('a:has-text("글쓰기")')
                if btn:
                    # target="_blank"일 수 있으므로 새 탭 처리
                    try:
                        async with context.expect_page(timeout=10000) as new_page_info:
                            await btn.click()
                        new_page = await new_page_info.value
                        await new_page.wait_for_load_state("domcontentloaded")
                        await asyncio.sleep(5)
                        print(f"  [접속] ✓ 새 탭으로 에디터 열림: {new_page.url[:80]}")
                        return True
                    except Exception:
                        await asyncio.sleep(3)
                        # 같은 탭에서 이동했을 수 있음
                        pages = context.pages
                        if len(pages) > 1:
                            print(f"  [접속] ✓ 새 탭 감지: {pages[-1].url[:80]}")
                            return True
            except Exception:
                continue

    return True


async def step2_inspect_editor(blog_id: str):
    """2단계: SmartEditor ONE 셀렉터 검사"""
    print("\n" + "=" * 60)
    print("  [2단계] SmartEditor ONE 셀렉터 검사")
    print(f"  블로그 아이디: {blog_id}")
    print("=" * 60 + "\n")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            args=STEALTH_ARGS,
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            ignore_default_args=["--enable-automation"],
        )
        await context.add_init_script(STEALTH_SCRIPT)

        page = context.pages[0] if context.pages else await context.new_page()

        # 글쓰기 페이지 접근 (로그인 리다이렉트 포함)
        accessed = await _ensure_blog_write_access(page, context, blog_id)
        if not accessed:
            print("  ⚠ 글쓰기 페이지 접근 실패. 종료합니다.")
            await context.close()
            return

        # 에디터 로드 대기
        await asyncio.sleep(5)

        print(f"  현재 URL: {page.url}")

        # mainFrame iframe 찾기 (SmartEditor ONE이 여기에 있음)
        editor_frame = None
        for frame in page.frames:
            if "PostWrite" in frame.url or "mainFrame" in (frame.name or ""):
                editor_frame = frame
                print(f"  ✓ 에디터 iframe 발견: name={frame.name}, url={frame.url[:80]}")
                break

        if not editor_frame:
            print("  ⚠ 에디터 iframe을 찾을 수 없습니다.")
            editor_frame = page  # 폴백: 메인 페이지에서 검색

        # 에디터 프레임에서 셀렉터 검사
        print("\n  [셀렉터 검사 결과] (에디터 iframe 내부)")
        print("  " + "-" * 50)

        selectors_to_check = {
            # 제목 관련
            "제목 영역 (se-documentTitle)": ".se-documentTitle-editView",
            "제목 텍스트 (se-text-paragraph in title)": ".se-documentTitle-editView .se-text-paragraph",
            "제목 placeholder": ".se-placeholder.__se_placeholder",

            # 본문 관련
            "본문 영역 (se-component-content)": ".se-component-content",
            "본문 편집 영역": ".se-content",
            "본문 텍스트 입력": ".se-text-paragraph",

            # 툴바 관련
            "이미지 버튼": "button.se-image-toolbar-button",
            "이미지 버튼 (alt1)": 'button[data-name="image"]',
            "이미지 버튼 (alt2)": '.se-toolbar-item-image button',
            "인용구 버튼": 'button[data-name="quotation"]',
            "인용구 버튼 (alt1)": '.se-toolbar-item-quotation button',
            "소제목 버튼": 'button[data-name="headingLevel"]',
            "소제목 버튼 (alt1)": '.se-toolbar-item-headingLevel button',

            # 발행 관련
            "발행 버튼 (상단)": 'button.publish_btn__Y9Fzb',
            "발행 버튼 (alt1)": '[class*="publish"] button',
            "발행 버튼 (alt2)": '.btn_publish',
            "발행 버튼 (alt3)": 'button:has-text("발행")',
        }

        found_selectors = {}

        for name, selector in selectors_to_check.items():
            try:
                el = await editor_frame.query_selector(selector)
                if el:
                    visible = await el.is_visible()
                    tag = await el.evaluate("el => el.tagName")
                    classes = await el.evaluate("el => el.className")
                    text_content = await el.evaluate("el => el.textContent?.slice(0, 50) || ''")
                    status = "✓ 발견" + (" (보임)" if visible else " (숨김)")
                    print(f"  {status} | {name}")
                    print(f"           | selector: {selector}")
                    print(f"           | tag: {tag}, class: {classes[:60]}")
                    if text_content.strip():
                        print(f"           | text: {text_content.strip()[:40]}")
                    found_selectors[name] = {"selector": selector, "visible": visible}
                else:
                    print(f"  ✗ 없음  | {name} → {selector}")
            except Exception as e:
                print(f"  ✗ 에러  | {name} → {str(e)[:60]}")

        # 페이지 전체 구조 덤프 (디버깅용)
        print("\n  [에디터 iframe 확인]")
        frames = page.frames
        print(f"  프레임 수: {len(frames)}")
        for i, frame in enumerate(frames):
            print(f"    [{i}] {frame.name or '(main)'} → {frame.url[:80]}")

        # 추가 셀렉터 탐색 (동적으로)
        print("\n  [동적 셀렉터 탐색]")
        try:
            # 모든 버튼 찾기
            buttons = await editor_frame.query_selector_all("button[class*='toolbar'], button[class*='se-']")
            print(f"  툴바 버튼 {len(buttons)}개 발견:")
            for btn in buttons[:20]:
                btn_text = await btn.evaluate("el => el.textContent?.trim() || ''")
                btn_class = await btn.evaluate("el => el.className")
                btn_name = await btn.evaluate("el => el.getAttribute('data-name') || ''")
                if btn_name or btn_text:
                    print(f"    - data-name=\"{btn_name}\" class=\"{btn_class[:50]}\" text=\"{btn_text[:20]}\"")
        except Exception as e:
            print(f"  동적 탐색 실패: {e}")

        # 발행 버튼 추가 탐색
        print("\n  [발행 버튼 추가 탐색]")
        try:
            all_btns = await editor_frame.query_selector_all("button")
            for btn in all_btns:
                text = await btn.evaluate("el => el.textContent?.trim() || ''")
                if "발행" in text or "저장" in text or "공개" in text:
                    cls = await btn.evaluate("el => el.className")
                    print(f"    발견: text=\"{text[:30]}\" class=\"{cls[:60]}\"")
        except Exception as e:
            print(f"  탐색 실패: {e}")

        print("\n  " + "-" * 50)
        print("  검사 완료. 10초 후 브라우저를 닫습니다...")
        await asyncio.sleep(10)

        # 결과 저장
        result_path = Path(__file__).parent / "storage" / "selector_report.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(found_selectors, f, ensure_ascii=False, indent=2)
        print(f"  결과 저장: {result_path}\n")

        await context.close()

    return found_selectors


async def step3_test_posting(blog_id: str, publish: bool = False):
    """3단계: 새 NaverBlogPublisher로 자동 포스팅 테스트"""
    print("\n" + "=" * 60)
    print("  [3단계] 자동 포스팅 테스트")
    print(f"  블로그 아이디: {blog_id}")
    print(f"  자동 발행: {'예' if publish else '아니오 (입력만, 60초 후 종료)'}")
    print("=" * 60 + "\n")

    # 최근 생성된 글 찾기
    posts_dir = Path(__file__).parent / "storage" / "posts"
    md_files = sorted(posts_dir.glob("*.md"), reverse=True)

    if not md_files:
        print("  ⚠ 생성된 글이 없습니다. 먼저 글을 생성하세요:")
        print("  python3 main_cli.py generate \"남이섬 벚꽃 축제\"")
        return

    latest = md_files[0]
    content = latest.read_text(encoding="utf-8")
    title = ""
    for line in content.split("\n"):
        if line.startswith("# "):
            title = line[2:].strip()
            break

    print(f"  사용할 글: {latest.name}")
    print(f"  제목: {title[:50]}...\n")

    # 브라우저 실행
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,
            args=STEALTH_ARGS,
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            ignore_default_args=["--enable-automation"],
        )
        await context.add_init_script(STEALTH_SCRIPT)
        page = context.pages[0] if context.pages else await context.new_page()

        # NaverBlogPublisher 사용
        from bots.naver_blog_publisher import NaverBlogPublisher

        publisher = NaverBlogPublisher(page)

        # 1. 에디터 접속 (로그인 포함)
        success = await publisher.navigate_to_editor(blog_id)
        if not success:
            print("  ⚠ 에디터 접속 실패. 종료합니다.")
            await context.close()
            return

        # 2. 콘텐츠 입력
        result = await publisher.publish(
            blog_id=blog_id,
            content_md=content,
            auto_publish=False,  # 일단 입력만
        )

        # 3. 발행 버튼 클릭 + 설정 패널 조사
        if publish:
            print("\n  [발행 프로세스 조사]")
            frame = publisher._get_editor_frame()

            # 발행 버튼 찾기 (모든 프레임)
            for f in page.frames:
                try:
                    btns = await f.query_selector_all("button")
                    for btn in btns:
                        text = await btn.evaluate("el => el.textContent?.trim() || ''")
                        if "발행" in text or "저장" in text:
                            cls = await btn.evaluate("el => el.className")
                            visible = await btn.is_visible()
                            print(f"    [{f.name or 'main'}] text=\"{text}\" class=\"{cls[:50]}\" visible={visible}")
                except Exception:
                    continue

            # 발행 버튼 클릭
            print("\n  → 발행 버튼 클릭...")
            clicked = False
            for f in page.frames:
                try:
                    btn = await f.query_selector('button[class*="publish_btn"]')
                    if btn and await btn.is_visible():
                        text = await btn.evaluate("el => el.textContent?.trim() || ''")
                        if "발행" in text and "예약" not in text:
                            await btn.click()
                            print(f"    ✓ 클릭: {text}")
                            clicked = True
                            break
                except Exception:
                    continue

            if clicked:
                await asyncio.sleep(3)

                # 발행 설정 패널 조사
                print("\n  [발행 설정 패널 조사]")
                for f in page.frames:
                    try:
                        # 패널 내 모든 버튼/요소 탐색
                        elements = await f.query_selector_all("button, [role='button'], a[class*='btn']")
                        for el in elements:
                            text = await el.evaluate("el => el.textContent?.trim() || ''")
                            cls = await el.evaluate("el => el.className || ''")
                            visible = await el.is_visible()
                            if visible and text:
                                tag = await el.evaluate("el => el.tagName")
                                print(f"    [{f.name or 'main'}] <{tag}> text=\"{text[:30]}\" class=\"{cls[:50]}\"")
                    except Exception:
                        continue

                # 30초 대기 — 브라우저에서 직접 확인
                print("\n  → 브라우저에서 발행 설정 패널을 확인하세요. (30초 대기)")
                await asyncio.sleep(30)

        await context.close()


def main():
    if len(sys.argv) < 2:
        print("사용법:")
        print("  python3 test_browser.py login              # 네이버 로그인")
        print("  python3 test_browser.py inspect <블로그ID>  # 셀렉터 검사")
        print("  python3 test_browser.py post <블로그ID>     # 글 입력 (발행X)")
        print("  python3 test_browser.py publish <블로그ID>  # 글 입력 + 발행")
        return

    cmd = sys.argv[1]

    if cmd == "login":
        asyncio.run(step1_login())
    elif cmd == "inspect":
        if len(sys.argv) < 3:
            print("블로그 아이디를 입력하세요: python3 test_browser.py inspect <블로그ID>")
            return
        asyncio.run(step2_inspect_editor(sys.argv[2]))
    elif cmd in ("post", "publish"):
        if len(sys.argv) < 3:
            print("블로그 아이디를 입력하세요: python3 test_browser.py post <블로그ID>")
            return
        asyncio.run(step3_test_posting(sys.argv[2], publish=(cmd == "publish")))
    else:
        print(f"알 수 없는 명령: {cmd}")


if __name__ == "__main__":
    main()
