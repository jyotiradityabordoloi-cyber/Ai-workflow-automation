from functools import lru_cache
from pathlib import Path

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
    # agent corrections in a ChromaDB vector store. "onnx" embeds with all-MiniLM-L6-v2 (downloaded once, ~80 MB,
    # runs locally); "hash" is a deterministic offline bag-of-words embedder for tests.
    memory_dir: Path = BACKEND_DIR / ".memory"
    embedding_provider: str = "onnx"
    memory_history_days: int = 90
    memory_history_limit: int = 5          # earlier tickets of the same customer shown to the classifier
    knowledge_min_similarity: float = 0.3  # below this a "similar resolved ticket" is noise
    correction_min_similarity: float = 0.6 # only near-duplicates of a corrected ticket steer the classifier

    cors_origins: list[str] = ["http://localhost:3000"]
    ticket_url_base: str = "http://localhost:3000/tickets"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
