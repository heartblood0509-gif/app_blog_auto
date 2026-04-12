"""
네이버 블로그 자동 포스팅 — SmartEditor ONE 자동화

핵심: SmartEditor ONE은 mainFrame iframe 안에 있음.
모든 셀렉터 조작은 editor_frame에서 수행해야 함.

실제 검증된 셀렉터 (2026-04-10):
- 제목 placeholder: .se-placeholder.__se_placeholder
- 본문 영역: .se-component-content
- 본문 편집: .se-content
- 텍스트 입력: .se-text-paragraph
- 이미지 버튼: button[data-name="image"]
- 인용구 버튼: button[data-name="quotation"]
- 발행 버튼: .publish_btn__m9KHH (iframe 밖, 메인 페이지)
- 저장 버튼: .save_btn__bzc5B (iframe 밖, 메인 페이지)
"""

import asyncio
import random
from pathlib import Path
from playwright.async_api import Frame, Page

from core.markdown_converter import BlockType, parse_markdown, parse_emphasis


# 레퍼런스 블로그 분석 기반 색상 팔레트 (포스트별 랜덤 선택)
ACCENT_COLORS = [
    "rgb(255, 95, 69)",   # 주황빨강
    "rgb(0, 78, 130)",    # 진파랑
    "rgb(186, 0, 0)",     # 진빨강
    "rgb(130, 63, 0)",    # 갈색
    "rgb(187, 0, 92)",    # 진분홍
    "rgb(0, 120, 203)",   # 파랑
]


class NaverBlogPublisher:
    """네이버 블로그 자동 발행기"""

    def __init__(self, page: Page):
        self.page = page
        self.editor_frame: Frame | None = None
        self.accent_color: str = random.choice(ACCENT_COLORS)

    def _get_editor_frame(self) -> Frame:
        """mainFrame iframe 찾기"""
        if self.editor_frame:
            return self.editor_frame
        for frame in self.page.frames:
            if "PostWrite" in frame.url or frame.name == "mainFrame":
                self.editor_frame = frame
                return frame
        raise RuntimeError("SmartEditor ONE iframe(mainFrame)을 찾을 수 없습니다.")

    async def _wait_for_editor_frame(self, timeout: int = 30) -> Frame:
        """에디터 iframe이 나타날 때까지 대기"""
        for i in range(timeout):
            for frame in self.page.frames:
                if "PostWrite" in frame.url or frame.name == "mainFrame":
                    self.editor_frame = frame
                    return frame
            await asyncio.sleep(1)
        raise RuntimeError("SmartEditor ONE iframe(mainFrame)을 찾을 수 없습니다.")

    async def _human_click(self, element):
        """요소 영역 내 랜덤 위치 클릭 (iframe 안에서도 안전)"""
        box = await element.bounding_box()
        if box:
            offset_x = random.uniform(box["width"] * 0.2, box["width"] * 0.8)
            offset_y = random.uniform(box["height"] * 0.25, box["height"] * 0.75)
            await element.click(position={"x": offset_x, "y": offset_y})
        else:
            await element.click()

    async def _human_type(self, text: str, delay_range: tuple[int, int] = (5, 15)):
        """인간형 타이핑"""
        for char in text:
            await self.page.keyboard.type(char, delay=random.randint(*delay_range))
            if random.random() < 0.08:
                await asyncio.sleep(random.uniform(0.05, 0.2))

    async def navigate_to_editor(self, blog_id: str) -> bool:
        """글쓰기 페이지로 이동 (로그인 리다이렉트 포함)"""
        write_url = f"https://blog.naver.com/{blog_id}?Redirect=Write"
        print(f"  [이동] → {write_url}")
        await self.page.goto(write_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # 로그인 리다이렉트 시 대기
        if "nidlogin" in self.page.url or "login" in self.page.url.lower():
            print("  [이동] 로그인 대기 중... (브라우저에서 로그인하세요)")
            for i in range(180):
                await asyncio.sleep(1)
                if "nidlogin" not in self.page.url and "login" not in self.page.url.lower():
                    print("  [이동] ✓ 로그인 완료")
                    break
                if (i + 1) % 30 == 0:
                    print(f"    ... {i + 1}초 경과")
            else:
                print("  [이동] ⚠ 로그인 타임아웃")
                return False

        await asyncio.sleep(5)

        # mainFrame iframe 확인
        try:
            frame = self._get_editor_frame()
            await frame.wait_for_selector(".se-content", timeout=15000)
            print(f"  [이동] ✓ SmartEditor ONE 로드 완료")
        except Exception as e:
            print(f"  [이동] ⚠ 에디터 로드 실패: {e}")
            return False

        # 팝업 닫기 (임시저장 복원 팝업 등)
        await self._dismiss_popups(frame)
        return True

    async def _dismiss_popups(self, frame: Frame):
        """에디터 위에 떠있는 팝업 닫기 (임시저장 복원 등)"""
        await asyncio.sleep(1)
        try:
            # "확인" 또는 "취소" 버튼 찾기
            for selector in [
                '.se-popup-alert-confirm button.se-popup-button-cancel',
                '.se-popup-alert button:has-text("취소")',
                '.se-popup-alert button:has-text("확인")',
                '.se-popup-button-cancel',
                'button.se-popup-button-cancel',
            ]:
                btn = await frame.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    print("  [이동] 팝업 닫음")
                    await asyncio.sleep(1)
                    return

            # 팝업 dim 레이어 클릭으로 닫기
            dim = await frame.query_selector('.se-popup-dim')
            if dim and await dim.is_visible():
                await dim.click()
                print("  [이동] 팝업 dim 클릭으로 닫음")
                await asyncio.sleep(1)
        except Exception:
            pass  # 팝업이 없으면 무시

    async def publish(
        self,
        blog_id: str,
        content_md: str,
        image_paths: list[Path] | None = None,
        auto_publish: bool = False,
        formatting_theme: dict | None = None,
    ) -> str | None:
        """마크다운 콘텐츠를 네이버 블로그에 발행

        Args:
            blog_id: 네이버 블로그 아이디
            content_md: 마크다운 형식의 블로그 글
            image_paths: 삽입할 이미지 파일 경로 목록
            auto_publish: True면 자동 발행, False면 입력만 (수동 발행)
            formatting_theme: 포맷팅 테마 (accent_color 등)

        Returns:
            발행된 글의 URL 또는 None
        """
        # 포맷팅 테마 적용
        if formatting_theme and formatting_theme.get("accent_color"):
            self.accent_color = formatting_theme["accent_color"]
            print(f"  🎨 테마: {formatting_theme.get('name', '?')} / 색상: {self.accent_color}")

        sequence = parse_markdown(content_md)
        image_paths = image_paths or []
        frame = self._get_editor_frame()

        print(f"\n[Blog] 포스팅 시작: {sequence.title[:40]}...")
        print(f"  블록: {len(sequence.blocks)}개, 이미지: {len(image_paths)}장")

        # 1. 제목 입력
        print("  [1/4] 제목 입력 중...")
        await self._input_title(frame, sequence.title)

        # 2. 본문 입력
        print("  [2/4] 본문 입력 중...")
        await self._input_body(frame, sequence.blocks, image_paths)

        # 3. 발행 또는 대기
        if auto_publish:
            print("  [3/4] 발행 중...")
            url = await self._click_publish(frame)
            if url:
                print(f"  [4/4] ✓ 발행 완료: {url}")
            else:
                print("  [4/4] ⚠ 발행 결과 확인 불가")
            return url
        else:
            print("  [3/4] 입력 완료! 브라우저에서 확인 후 수동 발행하세요.")
            print("  [4/4] 대기 중... (60초 후 종료)")
            await asyncio.sleep(60)
            return None

    async def _input_title(self, frame: Frame, title: str):
        """제목 입력"""
        try:
            # 제목 영역 클릭 (placeholder 클릭)
            title_placeholder = await frame.wait_for_selector(
                ".se-placeholder.__se_placeholder",
                timeout=5000,
            )
            if title_placeholder:
                await self._human_click(title_placeholder)
                await asyncio.sleep(0.5)

            # 제목 타이핑
            await self._human_type(title, delay_range=(10, 25))
            print(f"    ✓ 제목: {title[:40]}...")

        except Exception as e:
            # 폴백: 첫 번째 텍스트 단락 클릭
            print(f"    placeholder 실패, 폴백 시도: {e}")
            first_p = await frame.query_selector(".se-text-paragraph")
            if first_p:
                await self._human_click(first_p)
                await asyncio.sleep(0.3)
                await self._human_type(title, delay_range=(10, 25))

        # 본문으로 이동 — 본문 영역 직접 클릭
        await asyncio.sleep(0.5)
        try:
            # SmartEditor ONE: 본문은 .se-sections 안에 있고, 제목은 .se-documentTitle 안에 있음
            body_area = await frame.query_selector(".se-sections .se-text-paragraph")
            if not body_area:
                body_area = await frame.query_selector(".se-section-content .se-text-paragraph")
            if not body_area:
                # 제목 영역(.se-documentTitle) 바깥의 paragraph 찾기
                body_area = await frame.evaluate_handle("""
                    () => {
                        const all = document.querySelectorAll('.se-text-paragraph');
                        for (const el of all) {
                            if (!el.closest('.se-documentTitle')) return el;
                        }
                        return null;
                    }
                """)
                if await body_area.evaluate("el => el === null"):
                    body_area = None

            if body_area:
                await self._human_click(body_area)
                print("    ✓ 본문 영역 클릭 완료")
            else:
                await self.page.keyboard.press("Enter")
                print("    ⚠ 본문 영역 못 찾음, Enter로 이동")
        except Exception as e:
            print(f"    ⚠ 본문 이동 실패({e}), Enter로 이동")
            await self.page.keyboard.press("Enter")
        await asyncio.sleep(0.5)

    async def _insert_empty_line(self):
        """빈 줄(여백) 삽입"""
        await self.page.keyboard.press("Enter")
        await asyncio.sleep(0.1)

    async def _exit_quotation(self, frame: Frame):
        """인용구 밖으로 나가기 — 인용구 바로 아래에 커서 배치

        핵심: 마지막 paragraph가 아닌, 현재 인용구 컴포넌트의 바로 아래로 이동.
        방법: 인용구 컴포넌트의 bounding box 아래쪽을 클릭.
        """
        try:
            # 현재 활성화된 인용구 컴포넌트의 위치를 찾아서 바로 아래 클릭
            # 가장 마지막 인용구 = 방금 생성된 것
            quotations = await frame.query_selector_all('.se-component.se-quotation')
            if quotations:
                last_quote = quotations[-1]
                box = await last_quote.bounding_box()
                if box:
                    # 인용구 박스 바로 아래 (20px 아래) 클릭
                    click_x = box["x"] + box["width"] * 0.5
                    click_y = box["y"] + box["height"] + 20
                    await self.page.mouse.click(click_x, click_y)
                    await asyncio.sleep(0.5)
                    return True
        except Exception:
            pass

        try:
            # 폴백: .se-content 영역의 맨 아래 빈 공간 클릭
            content_area = await frame.query_selector('.se-content')
            if content_area:
                box = await content_area.bounding_box()
                if box:
                    click_x = box["x"] + box["width"] * 0.5
                    click_y = box["y"] + box["height"] - 10
                    await self.page.mouse.click(click_x, click_y)
                    await asyncio.sleep(0.5)
                    return True
        except Exception:
            pass

        # 최종 폴백: ArrowDown 반복으로 이동
        for _ in range(5):
            await self.page.keyboard.press("ArrowDown")
            await asyncio.sleep(0.1)
        await self.page.keyboard.press("End")
        await asyncio.sleep(0.2)
        return False

    async def _input_body(self, frame: Frame, blocks, image_paths: list[Path]):
        """본문 블록별 입력 — 가독성 패턴 적용

        참조 블로그 패턴: 소제목(볼드) → 빈줄 → 이미지 → 빈줄 → 본문 2~3줄 → 빈줄 반복
        """
        image_idx = 0
        total = len(blocks)

        for i, block in enumerate(blocks):
            if block.type == BlockType.PARAGRAPH:
                # 강조 마커 파싱
                plain_text, emphasis_phrases = parse_emphasis(block.text)
                # 문단 텍스트 입력 + 가독성 줄바꿈
                sentences = self._split_sentences(plain_text)
                for sentence in sentences:
                    await self._human_type(sentence, delay_range=(3, 8))
                    await self.page.keyboard.press("Enter")
                    await asyncio.sleep(0.1)
                # 문단 뒤 빈 줄
                await self._insert_empty_line()
                # 강조 문구가 있으면 색상+굵기 적용
                if emphasis_phrases:
                    await self._apply_emphasis(frame, emphasis_phrases)

            elif block.type == BlockType.HEADING:
                heading_style = getattr(block, 'quote_style', 'default') or 'default'
                await self._insert_heading(frame, block.text, quote_style=heading_style)

            elif block.type == BlockType.IMAGE:
                if image_idx < len(image_paths):
                    await self._insert_image(frame, image_paths[image_idx])
                    image_idx += 1

            elif block.type == BlockType.QUOTE:
                q_style = getattr(block, 'quote_style', 'default') or 'default'
                await self._insert_quote(frame, block.text, quote_style=q_style)

            elif block.type == BlockType.HORIZONTAL_RULE:
                await self._insert_horizontal_rule(frame)

            # 진행률 표시
            if (i + 1) % 5 == 0 or i == total - 1:
                print(f"    진행: {i + 1}/{total}")

            # 자연스러운 딜레이
            if i % 3 == 0:
                await asyncio.sleep(random.uniform(0.2, 0.6))

        print("    ✓ 본문 입력 완료")

    def _split_sentences(self, text: str) -> list[str]:
        """문단을 2~3문장씩 그룹으로 분리"""
        import re
        raw = re.split(r'(?<=[.!?~])\s+', text)
        if len(raw) <= 1:
            return [text]
        groups = []
        chunk = []
        for s in raw:
            chunk.append(s)
            if len(chunk) >= random.randint(2, 3):
                groups.append(" ".join(chunk))
                chunk = []
        if chunk:
            groups.append(" ".join(chunk))
        return groups

    async def _change_quotation_style(self, frame: Frame, style: str):
        """삽입된 인용구의 스타일을 JavaScript로 변경

        네이버 SmartEditor ONE 인용구 5종:
        - default: 큰따옴표 ("")
        - quotation_bubble: 말풍선
        - quotation_line: 세로선
        - quotation_underline: 밑줄
        - quotation_corner: 모서리 꺾쇠
        """
        style_class_map = {
            "default": "se-l-default",
            "bubble": "se-l-quotation_bubble",
            "line": "se-l-quotation_line",
            "underline": "se-l-quotation_underline",
            "corner": "se-l-quotation_corner",
        }
        target_class = style_class_map.get(style, "se-l-default")
        if target_class == "se-l-default":
            return  # 기본 스타일이면 변경 불필요

        result = await frame.evaluate(f"""
            () => {{
                const quotes = document.querySelectorAll('.se-component.se-quotation');
                const q = quotes[quotes.length - 1];
                if (!q) return 'no quotation';
                // 기존 레이아웃 클래스 제거 후 새 스타일 적용
                q.className = q.className.replace(/se-l-[\\w]+/, '{target_class}');
                return 'ok';
            }}
        """)
        if result == 'ok':
            print(f"      스타일 변경: {style}")
        else:
            print(f"      ⚠ 스타일 변경 실패({result})")

    async def _insert_heading(self, frame: Frame, text: str, quote_style: str = "default"):
        """소제목 삽입 — 인용구 스타일 선택 가능 + 본문 복귀

        인용구 5종 스타일 지원:
        - default: 큰따옴표, bubble: 말풍선, line: 세로선
        - underline: 밑줄, corner: 모서리 꺾쇠
        """
        # 소제목 전 여백
        await self._insert_empty_line()
        await self._insert_empty_line()

        # 인용구 버튼 클릭 (기본 스타일로 삽입)
        quote_btn = await frame.query_selector('button[data-name="quotation"]')
        if quote_btn:
            try:
                await quote_btn.click(timeout=5000)
            except Exception as e:
                print(f"    ⚠ 인용구 버튼 클릭 실패: {str(e)[:60]}, 볼드 폴백")
                await self._human_type(text, delay_range=(5, 12))
                await self.page.keyboard.press("Home")
                await self.page.keyboard.down("Shift")
                await self.page.keyboard.press("End")
                await self.page.keyboard.up("Shift")
                await asyncio.sleep(0.2)
                await self.page.keyboard.press("Meta+b")
                await asyncio.sleep(0.2)
                await self.page.keyboard.press("End")
                await self.page.keyboard.press("Enter")
                print(f"    ✓ 소제목(볼드 폴백): {text[:30]}...")
                return
            await asyncio.sleep(1.0)

            # ★ JavaScript로 인용구 내용에 직접 텍스트 삽입
            escaped = text.replace("\\", "\\\\").replace("'", "\\'")
            result = await frame.evaluate(f"""
                () => {{
                    const quotes = document.querySelectorAll('.se-component.se-quotation');
                    const q = quotes[quotes.length - 1];
                    if (!q) return 'no quotation';
                    const span = q.querySelector('.se-quote .se-text-paragraph span.__se-node');
                    if (!span) return 'no span';
                    span.textContent = '{escaped}';
                    const ph = q.querySelector('.se-quote .se-placeholder');
                    if (ph) ph.remove();
                    const mod = q.querySelector('.se-quote');
                    if (mod) mod.classList.remove('se-is-empty');
                    const para = q.querySelector('.se-quote .se-text-paragraph');
                    if (para) para.dispatchEvent(new InputEvent('input', {{bubbles:true, inputType:'insertText', data:'{escaped}'}}));
                    return 'ok';
                }}
            """)

            if result == 'ok':
                # 인용구 스타일 변경
                await self._change_quotation_style(frame, quote_style)
                print(f"    ✓ 소제목(인용구/{quote_style}): {text[:30]}...")
            else:
                print(f"    ⚠ 인용구 JS 삽입 실패({result}), 볼드 폴백")
                await self._human_type(text, delay_range=(5, 12))
                await self.page.keyboard.press("Home")
                await self.page.keyboard.down("Shift")
                await self.page.keyboard.press("End")
                await self.page.keyboard.up("Shift")
                await asyncio.sleep(0.2)
                await self.page.keyboard.press("Meta+b")
                await asyncio.sleep(0.2)
                await self.page.keyboard.press("End")
                await self.page.keyboard.press("Enter")

            # 인용구 밖으로 나가기
            await self._exit_quotation(frame)
            await asyncio.sleep(0.3)
        else:
            # 폴백: 볼드 텍스트
            await self._human_type(text, delay_range=(5, 12))
            await self.page.keyboard.press("Home")
            await self.page.keyboard.down("Shift")
            await self.page.keyboard.press("End")
            await self.page.keyboard.up("Shift")
            await asyncio.sleep(0.2)
            await self.page.keyboard.press("Meta+b")
            await asyncio.sleep(0.2)
            await self.page.keyboard.press("End")
            await self.page.keyboard.press("Enter")
            print(f"    ✓ 소제목(볼드): {text[:30]}...")

    async def _insert_image(self, frame: Frame, image_path: Path):
        """이미지 삽입 + 전후 여백"""
        await self._insert_empty_line()

        try:
            img_btn = await frame.query_selector('button[data-name="image"]')
            if not img_btn:
                img_btn = await frame.query_selector("button.se-image-toolbar-button")

            if img_btn:
                async with self.page.expect_file_chooser(timeout=10000) as fc_info:
                    await img_btn.click()
                file_chooser = await fc_info.value
                await file_chooser.set_files(str(image_path))
                await asyncio.sleep(3)

                # 이미지 삽입 후 본문 영역으로 돌아가기
                await self._click_below_component(frame)
                print(f"    ✓ 이미지: {image_path.name}")
            else:
                print("    ⚠ 이미지 버튼 없음")
        except Exception as e:
            print(f"    ⚠ 이미지 실패: {e}")

        await self._insert_empty_line()

    async def _insert_quote(self, frame: Frame, text: str, quote_style: str = "default"):
        """인용구 삽입 — 스타일 선택 가능 + 본문 복귀"""
        await self._insert_empty_line()

        quote_btn = await frame.query_selector('button[data-name="quotation"]')
        if not quote_btn:
            quote_btn = await frame.query_selector('button.se-toolbar-button-quotation')

        if quote_btn:
            try:
                await quote_btn.click(timeout=5000)
            except Exception as e:
                print(f"    ⚠ 인용구 버튼 클릭 실패: {str(e)[:60]}")
                await self._human_type(f"「 {text} 」", delay_range=(5, 12))
                await self.page.keyboard.press("Enter")
                print(f"    ✓ 인용구(텍스트 폴백): {text[:30]}...")
                await self._insert_empty_line()
                return
            await asyncio.sleep(1.0)

            await asyncio.sleep(1.0)

            # ★ JavaScript로 인용구 내용에 직접 텍스트 삽입
            escaped = text.replace("\\", "\\\\").replace("'", "\\'")
            result = await frame.evaluate(f"""
                () => {{
                    const quotes = document.querySelectorAll('.se-component.se-quotation');
                    const q = quotes[quotes.length - 1];
                    if (!q) return 'no quotation';
                    const span = q.querySelector('.se-quote .se-text-paragraph span.__se-node');
                    if (!span) return 'no span';
                    span.textContent = '{escaped}';
                    const ph = q.querySelector('.se-quote .se-placeholder');
                    if (ph) ph.remove();
                    const mod = q.querySelector('.se-quote');
                    if (mod) mod.classList.remove('se-is-empty');
                    const para = q.querySelector('.se-quote .se-text-paragraph');
                    if (para) para.dispatchEvent(new InputEvent('input', {{bubbles:true, inputType:'insertText', data:'{escaped}'}}));
                    return 'ok';
                }}
            """)

            if result == 'ok':
                # 인용구 스타일 변경
                await self._change_quotation_style(frame, quote_style)
                print(f"    ✓ 인용구({quote_style}): {text[:30]}...")
            else:
                print(f"    ⚠ 인용구 실패({result})")

            # 인용구 밖으로 나가기
            await self._exit_quotation(frame)
            await asyncio.sleep(0.3)
        else:
            # 폴백
            await self._human_type(f"「 {text} 」", delay_range=(5, 12))
            await self.page.keyboard.press("Enter")
            print(f"    ✓ 인용구(텍스트): {text[:30]}...")

        await self._insert_empty_line()

    async def _insert_horizontal_rule(self, frame: Frame):
        """구분선(수평선) 삽입 — 빈 줄 여백으로 섹션 구분

        SmartEditor ONE의 구분선 버튼은 툴바 접근이 불안정하므로,
        빈 줄 3개로 시각적 섹션 구분을 구현합니다.
        실제 인기 블로그에서도 빈 줄 + 인용구 조합이 더 자주 사용됩니다.
        """
        await self._insert_empty_line()
        await self._insert_empty_line()
        await self._insert_empty_line()
        print("    ✓ 구분선 (섹션 구분 여백)")

    async def _apply_emphasis(self, frame: Frame, phrases: list[str]):
        """방금 입력한 문단에서 특정 문구에 색상+굵기 강조 적용 (JS DOM 조작)

        SmartEditor ONE의 span 구조를 직접 조작하여
        강조 문구에 color + font-weight: bold 스타일을 적용합니다.
        """
        if not phrases:
            return

        color = self.accent_color
        # JS에서 사용할 문구 배열 생성 (특수문자 이스케이프)
        escaped_phrases = []
        for p in phrases:
            escaped = p.replace("\\", "\\\\").replace("'", "\\'")
            escaped_phrases.append(f"'{escaped}'")
        phrases_js = "[" + ",".join(escaped_phrases) + "]"

        result = await frame.evaluate(f"""
            () => {{
                const phrases = {phrases_js};
                const color = '{color}';
                const textComps = document.querySelectorAll('.se-component.se-text');
                if (textComps.length === 0) return 'no text components';

                // 최근 텍스트 컴포넌트들에서 강조 문구 검색 (마지막 3개)
                const searchRange = Math.min(3, textComps.length);
                let applied = 0;

                for (let ci = textComps.length - searchRange; ci < textComps.length; ci++) {{
                    const comp = textComps[ci];
                    const spans = comp.querySelectorAll('.se-text-paragraph span.__se-node');

                    spans.forEach(span => {{
                        let html = span.textContent;
                        let changed = false;

                        phrases.forEach(phrase => {{
                            if (html.includes(phrase)) {{
                                // textContent를 innerHTML로 전환하면서 강조 적용
                                const styledPhrase = '<span style="color: ' + color + '; font-weight: bold;">' + phrase + '</span>';
                                html = html.split(phrase).join(styledPhrase);
                                changed = true;
                                applied++;
                            }}
                        }});

                        if (changed) {{
                            span.innerHTML = html;
                        }}
                    }});
                }}

                return applied > 0 ? 'ok:' + applied : 'not found';
            }}
        """)

        if result and result.startswith('ok'):
            count = result.split(':')[1] if ':' in result else '?'
            print(f"      강조 적용: {count}건 ({color})")
        else:
            print(f"      ⚠ 강조 적용 실패({result})")

    async def _click_publish(self, frame: Frame) -> str | None:
        """발행 버튼 클릭 — 발행 버튼은 iframe 안과 메인 페이지 양쪽에서 탐색"""
        try:
            publish_btn = None

            # 1차: 에디터 iframe 내부에서 찾기
            for selector in [
                'button[class*="publish_btn"]',
                '[class*="publish_btn"] button',
            ]:
                publish_btn = await frame.query_selector(selector)
                if publish_btn and await publish_btn.is_visible():
                    break
                publish_btn = None

            # 2차: 메인 페이지 + 모든 프레임에서 찾기
            if not publish_btn:
                for f in self.page.frames:
                    for selector in [
                        'button[class*="publish_btn"]',
                        'button:has-text("발행")',
                    ]:
                        try:
                            btn = await f.query_selector(selector)
                            if btn:
                                text = await btn.evaluate("el => el.textContent?.trim() || ''")
                                if "발행" in text and "예약" not in text:
                                    publish_btn = btn
                                    print(f"    발행 버튼 발견: frame={f.name}, text={text}")
                                    break
                        except Exception:
                            continue
                    if publish_btn:
                        break

            if publish_btn:
                await publish_btn.click()
                await asyncio.sleep(3)

                # 발행 확인 다이얼로그 처리
                for f in self.page.frames:
                    try:
                        confirm_btn = await f.query_selector(
                            'button:has-text("발행"), button:has-text("확인")'
                        )
                        if confirm_btn and await confirm_btn.is_visible():
                            await confirm_btn.click()
                            await asyncio.sleep(5)
                            break
                    except Exception:
                        continue

                return self.page.url

            print("    ⚠ 발행 버튼을 찾을 수 없음")
            return None

        except Exception as e:
            print(f"    ⚠ 발행 에러: {e}")
            return None

    async def save_draft(self, frame: Frame) -> bool:
        """임시저장"""
        try:
            save_btn = await self.page.query_selector(
                'button[class*="save_btn"], button:has-text("저장")'
            )
            if save_btn:
                await save_btn.click()
                await asyncio.sleep(2)
                print("    ✓ 임시저장 완료")
                return True
        except Exception as e:
            print(f"    ⚠ 저장 실패: {e}")
        return False
