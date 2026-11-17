from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parents[1]


class Settings(BaseSettings):
    """Runtime configuration. Values come from env vars, then backend/.env, then the repo-root .env
    (so the existing GROQ_API_KEY is reused without copying secrets around)."""

    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"), extra="ignore")

    database_url: str = "postgresql+psycopg://supportflow:supportflow@localhost:5433/supportflow"

    llm_provider: str = "groq"  # "groq" or "fake" (deterministic, for tests and offline dev)
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"
    llm_reasoning_effort: str = "low"
    llm_timeout_s: float = 60
    llm_tpm_limit: int = 7500  # Groq free tier allows 8,000 tokens/min for gpt-oss-120b
    groq_api_key: str | None = None

    confidence_threshold: float = 0.7
    manager_keywords: tuple[str, ...] = ("legal", "lawyer", "refund", "chargeback")

    # Agent memory. Episodic = per-customer event history (PostgreSQL); semantic = resolved-ticket knowledge and
    # agent corrections in a vector store:
    #   memory_backend "chroma": a local folder (memory_dir), for development.
    #   memory_backend "qdrant": Qdrant at qdrant_url, for deployment (the API server keeps no state on disk).
    # embedding_provider: "onnx" = all-MiniLM-L6-v2 in-process (downloaded once, ~80 MB); "hash" = deterministic
    # offline embedder for tests; "qdrant-cloud" = the same MiniLM model run by Qdrant Cloud Inference (free tier).
    memory_backend: Literal["chroma", "qdrant"] = "chroma"
    memory_dir: Path = BACKEND_DIR / ".memory"
    embedding_provider: Literal["onnx", "hash", "qdrant-cloud"] = "onnx"
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    memory_history_days: int = 90
    memory_history_limit: int = 5          # earlier tickets of the same customer shown to the classifier
    knowledge_min_similarity: float = 0.3  # below this a "similar resolved ticket" is noise
    correction_min_similarity: float = 0.6 # only near-duplicates of a corrected ticket steer the classifier

    cors_origins: list[str] = ["http://localhost:3000"]
    ticket_url_base: str = "http://localhost:3000/tickets"
    log_level: str = "INFO"

    # Per-client-IP limits for a public demo, per 10 minutes (0 = off, the local default). "ai" counts requests that
    # call the LLM (create with analyze, re-analyze); "writes" counts every POST.
    rate_limit_ai_per_10min: int = 0
    rate_limit_writes_per_10min: int = 0

    @field_validator("database_url")
    @classmethod
    def _sqlalchemy_driver(cls, v: str) -> str:
        """Hosted Postgres (Neon, Render, Supabase) hands out postgres:// or postgresql:// URLs; use psycopg 3."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
