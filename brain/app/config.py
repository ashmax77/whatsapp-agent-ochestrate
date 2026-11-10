import os
from pathlib import Path
from typing import List
from pydantic import BaseModel, Field

# Base directory for brain
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env manually if python-dotenv is not installed
env_file = BASE_DIR / ".env"
if env_file.exists():
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    # Strip quotes if present
                    val = val.strip().strip("'").strip('"')
                    os.environ.setdefault(key.strip(), val)
    except Exception:
        pass


class Settings(BaseModel):
    PROJECT_NAME: str = "Pizza Hut WhatsApp Multi-Agent Brain"
    
    # LLM Settings
    LLM_PROVIDER: str = Field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openai"))
    OPENAI_API_KEY: str = Field(
        default_factory=lambda: os.getenv("OPENAI_KEY") or os.getenv("OPENAI_API_KEY", "")
    )
    ANTHROPIC_API_KEY: str = Field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", "")
    )
    CODECRAFT_KEY: str = Field(
        default_factory=lambda: os.getenv("CODECRAFT_KEY", "")
    )
    
    # Models
    ORCHESTRATOR_MODEL: str = Field(
        default_factory=lambda: os.getenv("ORCHESTRATOR_MODEL", "gpt-4o")
    )
    SUBAGENT_MODEL: str = Field(
        default_factory=lambda: os.getenv("SUBAGENT_MODEL", "gpt-4o-mini")
    )
    JUDGE_MODEL: str = Field(
        default_factory=lambda: os.getenv("JUDGE_MODEL", "gpt-4o")
    )
    EMBEDDING_MODEL: str = Field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    )

    # Paths
    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    MENU_FILE_PATH: Path = DATA_DIR / "menu.json"
    BRANCHES_FILE_PATH: Path = DATA_DIR / "branches.json"
    KB_PATH: Path = DATA_DIR / "knowledge"
    CHROMA_PATH: Path = DATA_DIR / "chroma"
    
    # RAG Configuration
    KB_EXCLUDE_DIRS: List[str] = ["internal"]
    KB_EXCLUDE_FILES: List[str] = ["README.md"]
    RAG_TOP_K: int = 4
    RAG_DISTANCE_CUTOFF: float = 0.65  # Cosine distance cutoff (1.0 - cosine_sim)

    # Business Rules & State
    MIN_ORDER_LKR: int = 1500
    TIMEZONE: str = "Asia/Colombo"
    LOG_LEVEL: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    MAX_TOOL_ITERATIONS: int = 6


settings = Settings()
