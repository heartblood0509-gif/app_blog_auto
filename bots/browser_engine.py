"""
Playwright 브라우저 엔진 — stealth mode + 자동 로그인 + 인간형 동작
"""

import asyncio
import random
from pathlib import Path

from playwright.async_api import (
    async_playwright,
    BrowserContext,
    Page,
    Playwright,
    Frame,
)

from config import settings


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
            Path(settings.CHROME_USER_DATA_DIR).resolve() / "default"
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

    async def auto_login(
        self,
        naver_id: str | None = None,
        naver_pw: str | None = None,
        target_url: str | None = None,
    ) -> bool:
        """네이버 자동 로그인 (클립보드 붙여넣기 방식)

        Args:
            naver_id: 네이버 아이디 (None이면 settings에서 가져옴)
            naver_pw: 네이버 비밀번호 (None이면 settings에서 가져옴)
            target_url: 로그인 후 이동할 URL (None이면 글쓰기 페이지)
        """
        uid = naver_id or settings.NAVER_ID
        pwd = naver_pw or settings.NAVER_PW
        blog_id = settings.NAVER_BLOG_ID

        if not uid or not pwd:
            print("  [로그인] ⚠ NAVER_ID/NAVER_PW가 .env에 설정되지 않았습니다.")
            return False

        page = self.page
        target = target_url or f"https://blog.naver.com/{blog_id}?Redirect=Write"

        # 1. 타겟 URL로 이동 (로그인 페이지로 리다이렉트됨)
        print(f"  [로그인] → {target[:60]}...")
        await page.goto(target, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # 이미 로그인된 경우
        if "nidlogin" not in page.url and "login" not in page.url.lower():
            print("  [로그인] ✓ 이미 로그인되어 있습니다.")
            return True

        print("  [로그인] 로그인 페이지 감지. 자동 로그인 시작...")

        # 2. 아이디 입력 (클립보드 붙여넣기)
        try:
            id_field = await page.wait_for_selector("#id", timeout=10000)
            if id_field:
                await id_field.click()
                await asyncio.sleep(0.3)
                # 기존 내용 지우기
                await page.keyboard.press("Meta+a")
                await asyncio.sleep(0.1)
                # 클립보드에 아이디 복사 후 붙여넣기
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
                '#log\\.login, button[type="submit"], .btn_login'
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
                # CAPTCHA 해결 대기 (2분)
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
