from pathlib import Path
from pydantic_settings import BaseSettings


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

    # Chrome
    CHROME_USER_DATA_DIR: str = "./storage/chrome_profiles"

    # Database
    DB_PATH: str = "./storage/app.db"

    # Posting
    POST_INTERVAL_MIN: int = 7
    POST_INTERVAL_MAX: int = 10
    FORBIDDEN_HOURS_START: int = 0
    FORBIDDEN_HOURS_END: int = 7
    IMAGE_COUNT: int = 6
    TARGET_CHAR_COUNT: int = 2000
    CHAR_COUNT_RANGE: str = "1500-2500"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    @property
    def base_dir(self) -> Path:
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


settings = Settings()
