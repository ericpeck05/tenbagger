"""App settings, read from the repo-root `.env` file.

Keys never get logged or returned by the API. Only whether each one is set.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    finnhub_api_key: SecretStr = SecretStr("")
    alpaca_key_id: SecretStr = SecretStr("")
    alpaca_secret_key: SecretStr = SecretStr("")
    sec_user_agent: SecretStr = SecretStr("")

    data_dir: Path = REPO_ROOT / "data"
    run_jobs: bool = True  # background quote loop and daily bars

    # Rate limits sit below each provider's published ceiling.
    edgar_per_second: float = Field(8, gt=0)
    finnhub_per_minute: int = Field(50, gt=0)
    alpaca_per_minute: int = Field(150, gt=0)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "tenbagger.db"

    def keys_present(self) -> dict[str, bool]:
        return {
            "finnhub": bool(self.finnhub_api_key.get_secret_value()),
            "alpaca": bool(
                self.alpaca_key_id.get_secret_value() and self.alpaca_secret_key.get_secret_value()
            ),
            "sec_user_agent": bool(self.sec_user_agent.get_secret_value()),
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
