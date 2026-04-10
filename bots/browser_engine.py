"""
Playwright 브라우저 엔진 — stealth mode + 자동 로그인 + 인간형 동작
"""

import asyncio
import os
import random
import sys
from pathlib import Path

from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Page,
    Playwright,
    Frame,
)

from config import settings

# PyInstaller 번들에서 Playwright 브라우저를 시스템 캐시에서 찾도록 설정
if getattr(sys, "frozen", False):
    _pw_cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    if _pw_cache.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_pw_cache)


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


class BrowserEngine:
    """Playwright 브라우저 엔진"""

    def __init__(self):
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    async def launch(self, profile_path: str | None = None) -> Page:
        """브라우저 실행"""
        if self._page and not self._page.is_closed():
            return self._page

        profile = profile_path or str(
            settings.chrome_profiles_dir / "default"
        )
        Path(profile).mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()

        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=profile,
            headless=False,
            args=STEALTH_ARGS,
            viewport={"width": 1280, "height": 900},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            ignore_default_args=["--enable-automation"],
        )

        await self._context.add_init_script(STEALTH_SCRIPT)
        self._page = (
            self._context.pages[0]
            if self._context.pages
            else await self._context.new_page()
        )
        return self._page

    @property
    def page(self) -> Page:
        if not self._page or self._page.is_closed():
            raise RuntimeError("브라우저가 실행되지 않았습니다.")
        return self._page

    @property
    def context(self) -> BrowserContext:
        if not self._context:
            raise RuntimeError("브라우저가 실행되지 않았습니다.")
        return self._context

    async def close(self):
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        self._context = None
        self._playwright = None
        self._page = None

    # ------------------------------------------------------------------
    # 자동 로그인
    # ------------------------------------------------------------------

    async def _is_logged_in(self) -> bool:
        """네이버 로그인 상태 확인"""
        page = self.page
        try:
            # 네이버 메인에서 로그인 여부 확인
            await page.goto("https://www.naver.com", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            # 로그인 상태면 .MyView-module__link_login 등이 없고 프로필 영역이 있음
            login_btn = await page.query_selector(
                'a.MyView-module__link_login___HpHMW, '
                'a[href*="nidlogin"], '
                '.MyView-module__loginBtn'
            )
            if login_btn and await login_btn.is_visible():
                return False
            return True
        except Exception:
            return False

    async def auto_login(
        self,
        naver_id: str | None = None,
        naver_pw: str | None = None,
    ) -> bool:
        """네이버 자동 로그인 (클립보드 붙여넣기 방식)"""
        uid = naver_id or settings.NAVER_ID
        pwd = naver_pw or settings.NAVER_PW

        if not uid or not pwd:
            print("  [로그인] ⚠ NAVER_ID/NAVER_PW가 설정되지 않았습니다.")
            return False

        page = self.page

        # 1. 로그인 페이지로 직접 이동
        login_url = "https://nid.naver.com/nidlogin.login?mode=form"
        print(f"  [로그인] 로그인 페이지 이동...")
        await page.goto(login_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # 이미 로그인된 상태면 (리다이렉트로 로그인 페이지를 벗어남)
        if "nidlogin" not in page.url and "login" not in page.url.lower():
            print("  [로그인] ✓ 이미 로그인되어 있습니다.")
            return True

        print("  [로그인] 자동 로그인 시작...")

        # 2. 아이디 입력 (클립보드 붙여넣기)
        try:
            id_field = await page.wait_for_selector("#id", timeout=10000)
            if id_field:
                await id_field.click()
                await asyncio.sleep(0.3)
                await page.keyboard.press("Meta+a")
                await asyncio.sleep(0.1)
                await page.evaluate(
                    f"navigator.clipboard.writeText('{uid}')"
                )
                await page.keyboard.press("Meta+v")
                await asyncio.sleep(0.5)

                # 클립보드 방식 실패 시 JS로 직접 설정
                current_val = await id_field.evaluate("el => el.value")
                if not current_val:
                    await page.evaluate(
                        f"""
                        const el = document.getElementById('id');
                        el.value = '{uid}';
                        el.dispatchEvent(new Event('input', {{bubbles: true}}));
                        """
                    )
                    await asyncio.sleep(0.3)

                print(f"  [로그인] 아이디 입력 완료")
        except Exception as e:
            print(f"  [로그인] ⚠ 아이디 입력 실패: {e}")
            return False

        # 3. 비밀번호 입력
        try:
            pw_field = await page.wait_for_selector("#pw", timeout=5000)
            if pw_field:
                await pw_field.click()
                await asyncio.sleep(0.3)
                await page.keyboard.press("Meta+a")
                await asyncio.sleep(0.1)
                await page.evaluate(
                    f"navigator.clipboard.writeText('{pwd}')"
                )
                await page.keyboard.press("Meta+v")
                await asyncio.sleep(0.5)

                # 폴백
                current_val = await pw_field.evaluate("el => el.value")
                if not current_val:
                    await page.evaluate(
                        f"""
                        const el = document.getElementById('pw');
                        el.value = '{pwd}';
                        el.dispatchEvent(new Event('input', {{bubbles: true}}));
                        """
                    )
                    await asyncio.sleep(0.3)

                print(f"  [로그인] 비밀번호 입력 완료")
        except Exception as e:
            print(f"  [로그인] ⚠ 비밀번호 입력 실패: {e}")
            return False

        # 4. 로그인 버튼 클릭
        try:
            login_btn = await page.query_selector(
                '#log\\.login, button[type="submit"], .btn_login, .btn_global'
            )
            if login_btn:
                await login_btn.click()
            else:
                await page.keyboard.press("Enter")

            print("  [로그인] 로그인 버튼 클릭")
        except Exception as e:
            print(f"  [로그인] 로그인 버튼 실패, Enter 시도: {e}")
            await page.keyboard.press("Enter")

        # 5. 로그인 결과 대기
        await asyncio.sleep(3)
        for i in range(60):
            await asyncio.sleep(1)
            url = page.url
            if "nidlogin" not in url and "login" not in url.lower():
                print(f"  [로그인] ✓ 로그인 성공! → {url[:60]}")
                return True

            # CAPTCHA 체크
            captcha = await page.query_selector("#captcha, .captcha, [class*='captcha']")
            if captcha:
                print("  [로그인] ⚠ CAPTCHA 감지! 브라우저에서 직접 해결하세요.")
                for j in range(120):
                    await asyncio.sleep(1)
                    if "nidlogin" not in page.url:
                        print("  [로그인] ✓ CAPTCHA 해결 후 로그인 성공!")
                        return True
                return False

            # 에러 메시지 체크
            error = await page.query_selector(".error_message, #err_common")
            if error and await error.is_visible():
                err_text = await error.evaluate("el => el.textContent?.trim() || ''")
                print(f"  [로그인] ⚠ 로그인 에러: {err_text}")
                return False

        print("  [로그인] ⚠ 로그인 타임아웃")
        return False

    async def _detect_blog_id(self, naver_id: str) -> str:
        """실제 블로그 ID 감지 (로그인 ID와 다를 수 있음)"""
        import re
        page = self.page

        # 네이버 시스템 경로 (블로그 ID가 아닌 것들)
        INVALID_IDS = {
            "BlogHome", "MyBlog", "PostWrite", "PostWriteForm",
            "PostView", "PostList", "NBlogTop", "section",
            "naver", "blog", "",
        }

        print(f"  [에디터] 블로그 ID 감지 중...")

        # 방법 1: MyBlog.naver → 로그인된 사용자의 블로그로 리다이렉트
        await page.goto("https://blog.naver.com/MyBlog.naver", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        await self._dismiss_blog_popups()

        current_url = page.url
        match = re.search(r"blog\.naver\.com/([A-Za-z0-9_]+)", current_url)
        if match and match.group(1) not in INVALID_IDS:
            detected_id = match.group(1)
            print(f"  [에디터] 블로그 ID 감지 (MyBlog): {detected_id}")
            return detected_id

        # 방법 2: 블로그 페이지에서 프로필 링크 추출
        try:
            profile_link = await page.query_selector('a[href*="blog.naver.com/"]')
            if profile_link:
                href = await profile_link.evaluate("el => el.href")
                match = re.search(r"blog\.naver\.com/([A-Za-z0-9_]+)", href)
                if match and match.group(1) not in INVALID_IDS:
                    detected_id = match.group(1)
                    print(f"  [에디터] 블로그 ID 감지 (프로필): {detected_id}")
                    return detected_id
        except Exception:
            pass

        # 방법 3: 제공된 ID를 그대로 사용
        print(f"  [에디터] 블로그 ID 자동 감지 실패, 입력값 사용: {naver_id}")
        return naver_id

    async def _dismiss_blog_popups(self):
        """블로그 페이지 팝업 닫기"""
        page = self.page
        await asyncio.sleep(1)
        try:
            # 공지 팝업 닫기 버튼들
            for selector in [
                'button:has-text("닫기")',
                'button:has-text("7일동안 보지 않기")',
                '.popup_close',
                '[class*="close"]',
                'button[aria-label="닫기"]',
                '.layer_close',
            ]:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    print("  [에디터] 팝업 닫음")
                    await asyncio.sleep(1)
                    return

            # X 버튼 (SVG 포함)
            close_btns = await page.query_selector_all('button')
            for btn in close_btns:
                try:
                    text = await btn.evaluate("el => el.textContent?.trim() || ''")
                    aria = await btn.evaluate("el => el.getAttribute('aria-label') || ''")
                    if '닫기' in text or '닫기' in aria or 'close' in aria.lower():
                        if await btn.is_visible():
                            await btn.click()
                            print("  [에디터] 팝업 닫음 (버튼 탐색)")
                            await asyncio.sleep(1)
                            return
                except Exception:
                    continue
        except Exception:
            pass

    async def _check_editor_loaded(self) -> bool:
        """에디터 iframe이 로드되었는지 확인"""
        for _ in range(15):
            for frame in self.page.frames:
                if "PostWrite" in frame.url or frame.name == "mainFrame":
                    return True
            await asyncio.sleep(1)
        return False

    async def navigate_to_editor(self, blog_id: str) -> bool:
        """로그인 후 글쓰기 에디터 페이지로 이동"""
        page = self.page

        # 실제 블로그 ID 감지
        detected_id = await self._detect_blog_id(blog_id)

        # 감지된 ID와 원래 ID 모두 시도할 후보
        candidates = list(dict.fromkeys([detected_id, blog_id]))  # 중복 제거, 순서 유지

        for bid in candidates:
            # 각 ID에 대해 여러 URL 패턴 시도
            editor_urls = [
                f"https://blog.naver.com/{bid}?Redirect=Write",
                f"https://blog.naver.com/PostWriteForm.naver?blogId={bid}",
            ]

            for url in editor_urls:
                print(f"  [에디터] 시도: {url[:70]}...")
                try:
                    await page.goto(url, wait_until="domcontentloaded")
                except Exception:
                    continue
                await asyncio.sleep(3)

                # "유효하지 않은 요청" 페이지 감지 → 즉시 다음 시도
                error_text = await page.evaluate(
                    "document.body?.innerText?.includes('유효하지 않은 요청') || false"
                )
                if error_text:
                    print(f"  [에디터] 유효하지 않은 블로그 ID, 다음 시도...")
                    continue

                await self._dismiss_blog_popups()

                if await self._check_editor_loaded():
                    print(f"  [에디터] ✓ 에디터 로드 성공! (blogId={bid})")
                    return True

                print(f"  [에디터] 에디터를 못 찾음, 다음 시도...")

        # 최종 시도: 글쓰기 버튼 찾아서 클릭
        print(f"  [에디터] URL 직접 접근 실패. 블로그에서 글쓰기 버튼 탐색...")
        await page.goto("https://blog.naver.com/MyBlog.naver", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        await self._dismiss_blog_popups()

        # "글쓰기" 버튼 찾기
        for selector in [
            'a:has-text("글쓰기")',
            'a[href*="Redirect=Write"]',
            'a[href*="postwrite"]',
            'a[href*="PostWrite"]',
            '.blog-menu a:has-text("글쓰기")',
        ]:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    print(f"  [에디터] 글쓰기 버튼 클릭!")
                    await asyncio.sleep(5)
                    if await self._check_editor_loaded():
                        print(f"  [에디터] ✓ 에디터 로드 성공! (글쓰기 버튼)")
                        return True
            except Exception:
                continue

        print(f"  [에디터] ⚠ 모든 시도 실패. 현재 URL: {page.url[:80]}")
        return False

    # ------------------------------------------------------------------
    # 인간형 동작 헬퍼
    # ------------------------------------------------------------------

    async def human_type(self, text: str, delay_range: tuple[int, int] = (5, 15)):
        for char in text:
            await self.page.keyboard.type(char, delay=random.randint(*delay_range))
            if random.random() < 0.08:
                await asyncio.sleep(random.uniform(0.05, 0.2))

    async def random_delay(self, min_s: float = 0.3, max_s: float = 1.0):
        await asyncio.sleep(random.uniform(min_s, max_s))
