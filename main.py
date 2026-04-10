"""
App_blog_auto — 네이버 블로그 자동 포스팅 GUI
"""

import asyncio
import sys
import threading
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QComboBox,
    QGroupBox, QProgressBar, QFrame,
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QFont

from config import settings

# ── 스타일시트 ──
STYLESHEET = """
QMainWindow {
    background-color: #FAFAFA;
}
QGroupBox {
    font-size: 15px;
    font-weight: bold;
    color: #333;
    border: 1px solid #E0E0E0;
    border-radius: 10px;
    margin-top: 14px;
    padding: 18px 14px 14px 14px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 6px;
}
QLineEdit {
    font-size: 15px;
    padding: 10px 12px;
    border: 1px solid #D0D0D0;
    border-radius: 8px;
    background: white;
}
QLineEdit:focus {
    border: 2px solid #03C75A;
}
QComboBox {
    font-size: 15px;
    padding: 8px 12px;
    border: 1px solid #D0D0D0;
    border-radius: 8px;
    background: white;
}
QLabel {
    font-size: 15px;
    color: #444;
}
QTextEdit {
    font-size: 13px;
    font-family: 'Menlo', 'Courier New', monospace;
    border: 1px solid #E0E0E0;
    border-radius: 8px;
    background: #1E1E1E;
    color: #D4D4D4;
    padding: 10px;
}
QProgressBar {
    border: none;
    border-radius: 6px;
    background: #E8E8E8;
    height: 12px;
    text-align: center;
    font-size: 0px;
}
QProgressBar::chunk {
    border-radius: 6px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #03C75A, stop:1 #00E676);
}
"""


class WorkerSignals(QObject):
    log = Signal(str)
    progress = Signal(int)
    finished = Signal(bool, str)
    content_ready = Signal(str, str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("네이버 블로그 자동 포스팅")
        self.setMinimumSize(720, 780)
        self.resize(720, 780)
        self.signals = WorkerSignals()
        self.signals.log.connect(self._append_log)
        self.signals.progress.connect(self._update_progress)
        self.signals.finished.connect(self._on_finished)
        self.signals.content_ready.connect(self._on_content_ready)

        self._generated_content = ""
        self._generated_title = ""
        self._is_running = False

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # ── 헤더 ──
        header = QLabel("네이버 블로그 자동 포스팅")
        header.setFont(QFont("", 22, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet("color: #03C75A; margin-bottom: 4px;")
        layout.addWidget(header)

        subtitle = QLabel("키워드를 입력하면 AI가 글을 작성하고 블로그에 자동 입력합니다")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("font-size: 13px; color: #888; margin-bottom: 8px;")
        layout.addWidget(subtitle)

        # ── 구분선 ──
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background: #E0E0E0; max-height: 1px;")
        layout.addWidget(line)

        # ── 계정 ──
        account_group = QGroupBox("계정 설정")
        acc_layout = QHBoxLayout(account_group)
        acc_layout.setSpacing(12)

        acc_layout.addWidget(QLabel("아이디"))
        self.input_naver_id = QLineEdit(settings.NAVER_ID)
        self.input_naver_id.setPlaceholderText("네이버 아이디")
        acc_layout.addWidget(self.input_naver_id, 1)

        acc_layout.addWidget(QLabel("비밀번호"))
        self.input_naver_pw = QLineEdit(settings.NAVER_PW)
        self.input_naver_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_naver_pw.setPlaceholderText("네이버 비밀번호")
        acc_layout.addWidget(self.input_naver_pw, 1)

        layout.addWidget(account_group)

        # ── 글 설정 ──
        content_group = QGroupBox("글 설정")
        content_layout = QVBoxLayout(content_group)
        content_layout.setSpacing(12)

        # 키워드 (크게)
        self.input_keyword = QLineEdit()
        self.input_keyword.setPlaceholderText("키워드 입력  (예: 남이섬 벚꽃 축제, 크루즈여행경비...)")
        self.input_keyword.setFont(QFont("", 17))
        self.input_keyword.setMinimumHeight(48)
        self.input_keyword.setStyleSheet(
            "QLineEdit { font-size: 17px; padding: 12px 14px; }"
            "QLineEdit:focus { border: 2px solid #03C75A; }"
        )
        content_layout.addWidget(self.input_keyword)

        # 템플릿 + 글자수
        opt_row = QHBoxLayout()
        opt_row.setSpacing(12)

        opt_row.addWidget(QLabel("글 스타일"))
        self.combo_template = QComboBox()
        self.combo_template.addItems([
            "후기/경험담",
            "정보/가이드",
            "브랜드 정보형",
            "브랜드 소개형",
        ])
        self.combo_template.setMinimumHeight(40)
        opt_row.addWidget(self.combo_template, 1)

        opt_row.addWidget(QLabel("글자수"))
        self.combo_charcount = QComboBox()
        self.combo_charcount.addItems(["짧게 (500~1500)", "보통 (1500~2500)", "길게 (2500~3500)"])
        self.combo_charcount.setCurrentIndex(1)
        self.combo_charcount.setMinimumHeight(40)
        opt_row.addWidget(self.combo_charcount, 1)

        content_layout.addLayout(opt_row)

        # 제품 정보
        prod_row = QHBoxLayout()
        prod_row.setSpacing(12)
        prod_row.addWidget(QLabel("제품명"))
        self.input_product = QLineEdit()
        self.input_product.setPlaceholderText("선택사항 — 비워두면 순수 정보글")
        prod_row.addWidget(self.input_product, 1)

        prod_row.addWidget(QLabel("장점"))
        self.input_advantages = QLineEdit()
        self.input_advantages.setPlaceholderText("선택사항")
        prod_row.addWidget(self.input_advantages, 1)
        content_layout.addLayout(prod_row)

        # 추가 요구사항
        req_row = QHBoxLayout()
        req_row.setSpacing(12)
        req_row.addWidget(QLabel("요구사항"))
        self.input_requirements = QLineEdit()
        self.input_requirements.setPlaceholderText("선택사항 — 예: 20대 여성 타겟, 오프닝에 결론 먼저...")
        req_row.addWidget(self.input_requirements, 1)
        content_layout.addLayout(req_row)

        layout.addWidget(content_group)

        # ── 실행 버튼 (1개) ──
        self.btn_start = QPushButton("글 생성 → 블로그 자동 입력")
        self.btn_start.setFont(QFont("", 17, QFont.Weight.Bold))
        self.btn_start.setMinimumHeight(56)
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #03C75A, stop:1 #00E676);
                color: white;
                border: none;
                border-radius: 12px;
                font-size: 17px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #02B350, stop:1 #00C853);
            }
            QPushButton:pressed {
                background: #029A46;
            }
            QPushButton:disabled {
                background: #BDBDBD;
                color: #F5F5F5;
            }
        """)
        self.btn_start.clicked.connect(self._on_start)
        layout.addWidget(self.btn_start)

        # ── 프로그레스 ──
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 14px; color: #666;")
        layout.addWidget(self.status_label)

        # ── 로그 ──
        log_group = QGroupBox("실행 로그")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(180)
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_group)

    def _get_template_id(self) -> str:
        return ["review", "informational", "brand-info", "brand-intro"][
            self.combo_template.currentIndex()
        ]

    def _get_char_range(self) -> str:
        return ["500-1500", "1500-2500", "2500-3500"][
            self.combo_charcount.currentIndex()
        ]

    # ------------------------------------------------------------------
    # 이벤트
    # ------------------------------------------------------------------

    def _on_start(self):
        keyword = self.input_keyword.text().strip()
        if not keyword:
            self._append_log("⚠ 키워드를 입력하세요!")
            return

        naver_id = self.input_naver_id.text().strip()
        naver_pw = self.input_naver_pw.text().strip()
        if not naver_id or not naver_pw:
            self._append_log("⚠ 네이버 아이디/비밀번호를 입력하세요!")
            return

        self._is_running = True
        self.btn_start.setEnabled(False)
        self.btn_start.setText("실행 중...")
        self.progress_bar.setValue(0)
        self.log_text.clear()
        self.status_label.setText("AI가 글을 생성하고 있습니다...")

        thread = threading.Thread(
            target=self._run_full_pipeline,
            args=(keyword, naver_id, naver_pw),
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------
    # 파이프라인 (글 생성 → 자동 입력)
    # ------------------------------------------------------------------

    def _run_full_pipeline(self, keyword: str, naver_id: str, naver_pw: str):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                self._async_pipeline(keyword, naver_id, naver_pw)
            )
        except Exception as e:
            self.signals.finished.emit(False, f"오류: {e}")
        finally:
            loop.close()

    async def _async_pipeline(self, keyword: str, naver_id: str, naver_pw: str):
        blog_id = naver_id  # 아이디 = 블로그ID

        # ── STEP 1: 글 생성 ──
        self.signals.log.emit(f"━━━ STEP 1: 글 생성 ━━━")
        self.signals.log.emit(f"키워드: {keyword}")
        self.signals.progress.emit(5)

        from core.content_generator import generate_from_keyword

        template = self._get_template_id()
        char_range = self._get_char_range()
        product = self.input_product.text().strip() or None
        advantages = self.input_advantages.text().strip() or None
        requirements = self.input_requirements.text().strip() or None

        self.signals.log.emit(f"스타일: {template} / 글자수: {char_range}")

        try:
            post = await generate_from_keyword(
                keyword=keyword,
                template=template,
                product_name=product,
                product_advantages=advantages,
                requirements=requirements,
                char_count_range=char_range,
            )
        except Exception as e:
            self.signals.finished.emit(False, f"글 생성 실패: {e}")
            return

        self._generated_content = post.content
        self._generated_title = post.title

        # 파일 저장
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_kw = keyword.replace(" ", "_")[:20]
        save_path = settings.posts_dir / f"{timestamp}_{safe_kw}.md"
        save_path.write_text(post.content, encoding="utf-8")

        self.signals.log.emit(f"✓ 제목: {post.title}")
        self.signals.log.emit(f"✓ 저장: {save_path.name}")
        self.signals.progress.emit(50)

        # ── STEP 2: 블로그 자동 입력 ──
        self.signals.log.emit(f"")
        self.signals.log.emit(f"━━━ STEP 2: 블로그 자동 입력 ━━━")

        from bots.browser_engine import BrowserEngine
        from bots.naver_blog_publisher import NaverBlogPublisher

        engine = BrowserEngine()
        try:
            self.signals.log.emit("브라우저 실행 중...")
            page = await engine.launch()
            self.signals.progress.emit(55)

            # 자동 로그인
            self.signals.log.emit("네이버 자동 로그인 중...")
            target_url = f"https://blog.naver.com/{blog_id}?Redirect=Write"
            logged_in = await engine.auto_login(naver_id, naver_pw, target_url)

            if not logged_in:
                self.signals.finished.emit(False, "로그인 실패. 아이디/비밀번호를 확인하세요.")
                return

            self.signals.log.emit("✓ 로그인 성공")
            self.signals.progress.emit(65)

            # 에디터 접속
            self.signals.log.emit("에디터 접속 중...")
            await asyncio.sleep(5)

            publisher = NaverBlogPublisher(page)

            try:
                frame = publisher._get_editor_frame()
                await frame.wait_for_selector(".se-content", timeout=15000)
            except Exception:
                await page.goto(target_url, wait_until="domcontentloaded")
                await asyncio.sleep(5)
                frame = publisher._get_editor_frame()
                await frame.wait_for_selector(".se-content", timeout=15000)

            await publisher._dismiss_popups(frame)
            self.signals.log.emit("✓ 에디터 로드 완료")
            self.signals.progress.emit(70)

            # 글 입력
            self.signals.log.emit("글 입력 시작...")
            await publisher.publish(
                blog_id=blog_id,
                content_md=self._generated_content,
                auto_publish=False,
            )

            self.signals.progress.emit(100)
            self.signals.finished.emit(
                True,
                "완료! 브라우저에서 확인 후 발행 버튼을 눌러주세요."
            )

        except Exception as e:
            self.signals.finished.emit(False, f"포스팅 실패: {e}")

    # ------------------------------------------------------------------
    # GUI 업데이트
    # ------------------------------------------------------------------

    def _append_log(self, msg: str):
        t = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"<span style='color:#888'>[{t}]</span> {msg}")

    def _update_progress(self, value: int):
        self.progress_bar.setValue(value)

    def _on_content_ready(self, title: str, content: str):
        self._generated_title = title
        self._generated_content = content

    def _on_finished(self, success: bool, message: str):
        self._is_running = False
        self.btn_start.setEnabled(True)
        self.btn_start.setText("글 생성 → 블로그 자동 입력")

        if success:
            self._append_log(f"")
            self._append_log(f"✅ {message}")
            self.status_label.setText("✅ " + message)
            self.status_label.setStyleSheet("font-size: 14px; color: #03C75A; font-weight: bold;")
        else:
            self._append_log(f"")
            self._append_log(f"❌ {message}")
            self.status_label.setText("❌ " + message)
            self.status_label.setStyleSheet("font-size: 14px; color: #E53935; font-weight: bold;")


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
