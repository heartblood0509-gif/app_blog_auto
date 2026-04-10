import sys
from pathlib import Path
from pydantic_settings import BaseSettings

# PyInstaller 번들 여부에 따라 프로젝트 루트 결정
if getattr(sys, "frozen", False):
    _PROJECT_DIR = Path(sys.executable).resolve().parent.parent.parent  # .app/Contents/MacOS → .app → dist → 프로젝트
    # dist 폴더 기준이면 한 단계 위가 프로젝트
    _env_candidates = [
        _PROJECT_DIR / ".env",
        _PROJECT_DIR.parent / ".env",
        Path.home() / ".blog_auto.env",
    ]
    _ENV_FILE = next((p for p in _env_candidates if p.exists()), str(Path(__file__).parent / ".env"))
else:
    _ENV_FILE = str(Path(__file__).parent / ".env")


class Settings(BaseSettings):
    # AI
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL_GENERATION: str = "gemini-2.5-flash"
    GEMINI_MODEL_ANALYSIS: str = "gemini-2.5-pro"

    # Image Generation
    FAL_API_KEY: str = ""
    UNSPLASH_ACCESS_KEY: str = ""

    # Naver
    NAVER_BLOG_ID: str = ""
    NAVER_ID: str = ""
    NAVER_PW: str = ""

    # Chrome (실제 경로는 chrome_profiles_dir 프로퍼티 사용)
    CHROME_USER_DATA_DIR: str = ""

    # Database
    DB_PATH: str = ""

    # Posting
    POST_INTERVAL_MIN: int = 7
    POST_INTERVAL_MAX: int = 10
    FORBIDDEN_HOURS_START: int = 0
    FORBIDDEN_HOURS_END: int = 7
    IMAGE_COUNT: int = 6
    TARGET_CHAR_COUNT: int = 2000
    CHAR_COUNT_RANGE: str = "1500-2500"

    model_config = {
        "env_file": str(_ENV_FILE),
        "env_file_encoding": "utf-8",
    }

    @property
    def base_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path.home() / ".blog_auto"
        return Path(__file__).parent

    @property
    def storage_dir(self) -> Path:
        path = self.base_dir / "storage"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def images_dir(self) -> Path:
        path = self.storage_dir / "images"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def posts_dir(self) -> Path:
        path = self.storage_dir / "posts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def chrome_profiles_dir(self) -> Path:
        if self.CHROME_USER_DATA_DIR:
            return Path(self.CHROME_USER_DATA_DIR).resolve()
        # .app과 main.py 모두 동일한 크롬 프로필 사용 (로그인 쿠키 공유)
        path = Path.home() / ".blog_auto" / "storage" / "chrome_profiles"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def db_path(self) -> Path:
        if self.DB_PATH:
            return Path(self.DB_PATH).resolve()
        return self.storage_dir / "app.db"


settings = Settings()
