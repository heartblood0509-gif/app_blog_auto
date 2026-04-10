"""
App_blog_auto — 네이버 블로그 자동 포스팅 GUI
"""

import asyncio
import os
import sys
import threading
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# PyInstaller 번들: Playwright 브라우저를 시스템 캐시에서 찾도록 설정
if getattr(sys, "frozen", False):
    _pw_cache = Path.home() / "Library" / "Caches" / "ms-playwright"
    if _pw_cache.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_pw_cache)

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QTextEdit, QPushButton, QComboBox,
    QGroupBox, QProgressBar, QFrame, QDialog, QDialogButtonBox,
    QMessageBox,
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
    font-size: 12px;
    font-weight: bold;
    color: #333;
    border: 1px solid #E0E0E0;
    border-radius: 8px;
    margin-top: 11px;
    padding: 14px 11px 11px 11px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 13px;
    padding: 0 5px;
}
QLineEdit {
    font-size: 13px;
    padding: 7px 10px;
    border: 1px solid #D0D0D0;
    border-radius: 6px;
    background: white;
    min-height: 18px;
}
QLineEdit:focus {
    border: 2px solid #03C75A;
}
QComboBox {
    font-size: 13px;
    padding: 7px 10px;
    border: 1px solid #D0D0D0;
    border-radius: 6px;
    background: white;
    min-height: 18px;
    combobox-popup: 0;
}
QComboBox QAbstractItemView {
    font-size: 13px;
    padding: 4px;
    border: 1px solid #D0D0D0;
    border-radius: 6px;
    background: white;
    selection-background-color: #E8F5E9;
    selection-color: #222;
    outline: none;
}
QComboBox QAbstractItemView::item {
    padding: 10px 14px;
    min-height: 32px;
}
QLabel {
    font-size: 13px;
    color: #444;
}
QTextEdit {
    font-size: 11px;
    font-family: 'Menlo', 'Courier New', monospace;
    border: 1px solid #E0E0E0;
    border-radius: 6px;
    background: #1E1E1E;
    color: #D4D4D4;
    padding: 8px;
}
QProgressBar {
    border: none;
    border-radius: 5px;
    background: #E8E8E8;
    height: 10px;
    text-align: center;
    font-size: 0px;
}
QProgressBar::chunk {
    border-radius: 5px;
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
        self.setMinimumSize(800, 900)
        self.resize(800, 900)
        self.signals = WorkerSignals()
        self.signals.log.connect(self._append_log)
        self.signals.progress.connect(self._update_progress)
        self.signals.finished.connect(self._on_finished)
        self.signals.content_ready.connect(self._on_content_ready)

        self._generated_content = ""
        self._generated_title = ""
        self._is_running = False

        self._build_ui()
        self._load_saved_account()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(19, 16, 19, 16)
        layout.setSpacing(13)

        # ── 헤더 ──
        header = QLabel("네이버 블로그 자동 포스팅")
        header.setFont(QFont("", 18, QFont.Weight.Bold))
        header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setStyleSheet("color: #03C75A; margin-bottom: 4px;")
        layout.addWidget(header)

        subtitle = QLabel("키워드를 입력하면 AI가 글을 작성하고 블로그에 자동 입력합니다")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("font-size: 11px; color: #888; margin-bottom: 6px;")
        layout.addWidget(subtitle)

        # ── 구분선 ──
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background: #E0E0E0; max-height: 1px;")
        layout.addWidget(line)

        # ── 계정 ──
        account_group = QGroupBox("계정 설정")
        acc_layout = QVBoxLayout(account_group)
        acc_layout.setSpacing(8)

        acc_row1 = QHBoxLayout()
        acc_row1.setSpacing(10)
        acc_row1.addWidget(QLabel("아이디"))
        self.input_naver_id = QLineEdit(settings.NAVER_ID)
        self.input_naver_id.setPlaceholderText("네이버 로그인 아이디")
        acc_row1.addWidget(self.input_naver_id, 1)

        acc_row1.addWidget(QLabel("비밀번호"))
        self.input_naver_pw = QLineEdit(settings.NAVER_PW)
        self.input_naver_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.input_naver_pw.setPlaceholderText("네이버 비밀번호")
        acc_row1.addWidget(self.input_naver_pw, 1)
        acc_layout.addLayout(acc_row1)

        acc_row2 = QHBoxLayout()
        acc_row2.setSpacing(10)
        acc_row2.addWidget(QLabel("블로그 ID"))
        self.input_blog_id = QLineEdit(settings.NAVER_BLOG_ID)
        self.input_blog_id.setPlaceholderText("블로그 ID (로그인 ID와 다르면 입력)")
        acc_row2.addWidget(self.input_blog_id, 1)
        acc_layout.addLayout(acc_row2)

        layout.addWidget(account_group)

        # ── 글 설정 ──
        content_group = QGroupBox("글 설정")
        content_layout = QVBoxLayout(content_group)
        content_layout.setSpacing(10)

        # 글 주제
        topic_row = QHBoxLayout()
        topic_row.setSpacing(10)
        topic_row.addWidget(QLabel("글 주제"))
        self.input_keyword = QLineEdit()
        self.input_keyword.setPlaceholderText("예: 탈모샴푸 후기, 크루즈여행 비용 비교...")
        topic_row.addWidget(self.input_keyword, 1)
        content_layout.addLayout(topic_row)

        # 키워드
        kw_row = QHBoxLayout()
        kw_row.setSpacing(10)
        kw_row.addWidget(QLabel("키워드"))
        self.input_seo_keyword = QLineEdit()
        self.input_seo_keyword.setPlaceholderText("선택사항 — 예: 탈모샴푸, 크루즈여행경비 (SEO용)")
        kw_row.addWidget(self.input_seo_keyword, 1)
        content_layout.addLayout(kw_row)

        # 템플릿 + 글자수
        opt_row = QHBoxLayout()
        opt_row.setSpacing(10)

        opt_row.addWidget(QLabel("글 스타일"))
        self.combo_template = QComboBox()
        self.combo_template.addItems([
            "후기/경험담",
            "정보/가이드",
            "브랜드 정보형",
            "브랜드 소개형",
        ])
        opt_row.addWidget(self.combo_template, 1)

        opt_row.addWidget(QLabel("글자수"))
        self.combo_charcount = QComboBox()
        self.combo_charcount.addItems(["짧게 (500~1500)", "보통 (1500~2500)", "길게 (2500~3500)"])
        self.combo_charcount.setCurrentIndex(1)
        opt_row.addWidget(self.combo_charcount, 1)

        content_layout.addLayout(opt_row)

        # 제품 정보
        prod_row = QHBoxLayout()
        prod_row.setSpacing(10)
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
        req_row.setSpacing(10)
        req_row.addWidget(QLabel("요구사항"))
        self.input_requirements = QLineEdit()
        self.input_requirements.setPlaceholderText("선택사항 — 예: 20대 여성 타겟, 오프닝에 결론 먼저...")
        req_row.addWidget(self.input_requirements, 1)
        content_layout.addLayout(req_row)

        layout.addWidget(content_group)

        # ── 실행 버튼 (1개) ──
        self.btn_start = QPushButton("글 생성 → 블로그 자동 입력")
        self.btn_start.setFont(QFont("", 13, QFont.Weight.Bold))
        self.btn_start.setMinimumHeight(40)
        self.btn_start.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_start.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #03C75A, stop:1 #00E676);
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 13px;
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

        # ── 다시 쓰기 버튼 (완료 후 표시) ──
        self.btn_reset = QPushButton("다시 쓰기")
        self.btn_reset.setFont(QFont("", 13, QFont.Weight.Bold))
        self.btn_reset.setMinimumHeight(40)
        self.btn_reset.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_reset.setStyleSheet("""
            QPushButton {
                background: white;
                color: #03C75A;
                border: 2px solid #03C75A;
                border-radius: 10px;
                font-size: 13px;
            }
            QPushButton:hover {
                background: #E8F5E9;
            }
        """)
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_reset.hide()
        layout.addWidget(self.btn_reset)

        # ── 프로그레스 ──
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("font-size: 11px; color: #666;")
        layout.addWidget(self.status_label)

        # ── 로그 ──
        log_group = QGroupBox("실행 로그")
        log_layout = QVBoxLayout(log_group)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(220)
        log_layout.addWidget(self.log_text)
        layout.addWidget(log_group)

        # ── API 키 설정 버튼 ──
        self.btn_api_key = QPushButton("API 키 설정")
        self.btn_api_key.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_api_key.setStyleSheet("""
            QPushButton {
                background: transparent;
                color: #888;
                border: 1px solid #D0D0D0;
                border-radius: 6px;
                font-size: 11px;
                padding: 6px 14px;
            }
            QPushButton:hover {
                background: #F0F0F0;
                color: #444;
            }
        """)
        self.btn_api_key.clicked.connect(self._on_api_key_settings)
        layout.addWidget(self.btn_api_key, alignment=Qt.AlignmentFlag.AlignRight)

    def _load_saved_account(self):
        """저장된 계정 정보 불러오기"""
        env_path = Path.home() / ".blog_auto.env"
        if env_path.exists():
            existing = self._load_env()
            naver_id = existing.get("NAVER_ID", "")
            naver_pw = existing.get("NAVER_PW", "")
            blog_id = existing.get("NAVER_BLOG_ID", "")
            if naver_id and not self.input_naver_id.text():
                self.input_naver_id.setText(naver_id)
            if naver_pw and not self.input_naver_pw.text():
                self.input_naver_pw.setText(naver_pw)
            if blog_id and not self.input_blog_id.text():
                self.input_blog_id.setText(blog_id)

    def _get_template_id(self) -> str:
        return ["review", "informational", "brand-info", "brand-intro"][
            self.combo_template.currentIndex()
        ]

    def _get_char_range(self) -> str:
        return ["500-1500", "1500-2500", "2500-3500"][
            self.combo_charcount.currentIndex()
        ]

    # ------------------------------------------------------------------
    # API 키 설정
    # ------------------------------------------------------------------

    def _load_env(self) -> dict[str, str]:
        env_path = Path.home() / ".blog_auto.env"
        existing = {}
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()
        return existing

    def _on_api_key_settings(self):
        env_path = Path.home() / ".blog_auto.env"
        existing = self._load_env()

        dialog = QDialog(self)
        dialog.setWindowTitle("설정")
        dialog.setMinimumWidth(450)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setSpacing(10)

        info = QLabel("설정은 홈 디렉토리에 로컬 저장됩니다. 외부로 전송되지 않습니다.")
        info.setStyleSheet("font-size: 11px; color: #888;")
        dlg_layout.addWidget(info)

        # 계정 설정
        acc_group = QGroupBox("네이버 계정")
        acc_layout = QVBoxLayout(acc_group)
        acc_layout.setSpacing(8)

        id_row = QHBoxLayout()
        id_row.addWidget(QLabel("아이디"))
        input_naver_id = QLineEdit(existing.get("NAVER_ID", ""))
        input_naver_id.setPlaceholderText("네이버 아이디")
        id_row.addWidget(input_naver_id, 1)
        acc_layout.addLayout(id_row)

        pw_row = QHBoxLayout()
        pw_row.addWidget(QLabel("비밀번호"))
        input_naver_pw = QLineEdit(existing.get("NAVER_PW", ""))
        input_naver_pw.setPlaceholderText("네이버 비밀번호")
        input_naver_pw.setEchoMode(QLineEdit.EchoMode.Password)
        pw_row.addWidget(input_naver_pw, 1)
        acc_layout.addLayout(pw_row)

        blog_row = QHBoxLayout()
        blog_row.addWidget(QLabel("블로그 ID"))
        input_blog_id = QLineEdit(existing.get("NAVER_BLOG_ID", ""))
        input_blog_id.setPlaceholderText("로그인 ID와 다르면 입력")
        blog_row.addWidget(input_blog_id, 1)
        acc_layout.addLayout(blog_row)

        dlg_layout.addWidget(acc_group)

        # API 키 설정
        api_group = QGroupBox("API 키")
        api_layout = QVBoxLayout(api_group)
        api_layout.setSpacing(8)

        gem_row = QHBoxLayout()
        gem_row.addWidget(QLabel("Gemini"))
        input_gemini = QLineEdit(existing.get("GEMINI_API_KEY", ""))
        input_gemini.setPlaceholderText("Gemini API 키 입력")
        input_gemini.setEchoMode(QLineEdit.EchoMode.Password)
        gem_row.addWidget(input_gemini, 1)
        api_layout.addLayout(gem_row)

        dlg_layout.addWidget(api_group)

        # 버튼
        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        dlg_layout.addWidget(btn_box)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            naver_id = input_naver_id.text().strip()
            naver_pw = input_naver_pw.text().strip()
            blog_id = input_blog_id.text().strip()
            gemini_key = input_gemini.text().strip()

            if naver_id:
                existing["NAVER_ID"] = naver_id
            if naver_pw:
                existing["NAVER_PW"] = naver_pw
            if blog_id:
                existing["NAVER_BLOG_ID"] = blog_id
            if gemini_key:
                existing["GEMINI_API_KEY"] = gemini_key

            lines = [f"{k}={v}" for k, v in existing.items()]
            env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

            # GUI에도 즉시 반영
            if naver_id:
                self.input_naver_id.setText(naver_id)
            if naver_pw:
                self.input_naver_pw.setText(naver_pw)
            if blog_id:
                self.input_blog_id.setText(blog_id)

            QMessageBox.information(self, "저장 완료", "설정이 저장되었습니다.")

    # ------------------------------------------------------------------
    # 이벤트
    # ------------------------------------------------------------------

    def _on_reset(self):
        """다시 쓰기 — 입력 폼 초기화"""
        self.input_keyword.clear()
        self.input_seo_keyword.clear()
        self.input_product.clear()
        self.input_advantages.clear()
        self.input_requirements.clear()
        self.combo_template.setCurrentIndex(0)
        self.combo_charcount.setCurrentIndex(1)
        self.progress_bar.setValue(0)
        self.status_label.setText("")
        self.status_label.setStyleSheet("font-size: 11px; color: #666;")
        self.log_text.clear()
        self.btn_reset.hide()
        self.btn_start.setEnabled(True)
        self.btn_start.setText("글 생성 → 블로그 자동 입력")
        self._generated_content = ""
        self._generated_title = ""

    def _on_start(self):
        topic = self.input_keyword.text().strip()
        if not topic:
            self._append_log("⚠ 글 주제를 입력하세요!")
            return

        seo_keyword = self.input_seo_keyword.text().strip()

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

        blog_id = self.input_blog_id.text().strip() or naver_id

        thread = threading.Thread(
            target=self._run_full_pipeline,
            args=(topic, seo_keyword, naver_id, naver_pw, blog_id),
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------
    # 파이프라인 (글 생성 → 자동 입력)
    # ------------------------------------------------------------------

    def _run_full_pipeline(self, topic: str, seo_keyword: str, naver_id: str, naver_pw: str, blog_id: str):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                self._async_pipeline(topic, seo_keyword, naver_id, naver_pw, blog_id)
            )
        except Exception as e:
            self.signals.finished.emit(False, f"오류: {e}")
        finally:
            loop.close()

    async def _async_pipeline(self, topic: str, seo_keyword: str, naver_id: str, naver_pw: str, blog_id: str):

        # ── STEP 1: 글 생성 ──
        self.signals.log.emit(f"━━━ STEP 1: 글 생성 ━━━")
        self.signals.log.emit(f"글 주제: {topic}")
        if seo_keyword:
            self.signals.log.emit(f"키워드: {seo_keyword}")
        self.signals.progress.emit(5)

        from core.content_generator import generate_from_keyword

        template = self._get_template_id()
        char_range = self._get_char_range()
        product = self.input_product.text().strip() or None
        advantages = self.input_advantages.text().strip() or None
        requirements = self.input_requirements.text().strip() or None
        # 키워드가 있으면 요구사항에 포함시켜 AI에 전달
        if seo_keyword:
            kw_req = f"다음 키워드를 자연스럽게 포함해주세요: {seo_keyword}"
            requirements = f"{requirements}. {kw_req}" if requirements else kw_req

        self.signals.log.emit(f"스타일: {template} / 글자수: {char_range}")

        try:
            post = await generate_from_keyword(
                keyword=topic,
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
        safe_kw = topic.replace(" ", "_")[:20]
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
            logged_in = await engine.auto_login(naver_id, naver_pw)

            if not logged_in:
                self.signals.finished.emit(False, "로그인 실패. 아이디/비밀번호를 확인하세요.")
                return

            self.signals.log.emit("✓ 로그인 성공")
            self.signals.progress.emit(65)

            # 에디터 접속
            self.signals.log.emit("에디터 접속 중...")
            editor_found = await engine.navigate_to_editor(blog_id)

            if not editor_found:
                self.signals.finished.emit(False, "에디터 페이지에 접근할 수 없습니다. 블로그 ID를 확인하세요.")
                return

            publisher = NaverBlogPublisher(page)
            frame = await publisher._wait_for_editor_frame(timeout=15)
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
        self.btn_start.setEnabled(False)
        self.btn_start.setText("완료")
        self.btn_reset.show()

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
