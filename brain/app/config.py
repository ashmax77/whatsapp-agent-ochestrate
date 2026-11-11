import os
from pathlib import Path
from typing import Dict, List
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
                    # Strip inline comments (e.g. # comment)
                    if " #" in val:
                        val = val.split(" #", 1)[0]
                    elif "\t#" in val:
                        val = val.split("\t#", 1)[0]
                    # Strip quotes if present
                    val = val.strip().strip("'").strip('"')
                    os.environ.setdefault(key.strip(), val)
    except Exception:
        pass


class Settings(BaseModel):
    
    PROJECT_NAME: str = "Pizza Hut WhatsApp Multi-Agent Brain"
    
    # LLM Settings
    LLM_PROVIDER: str = Field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openai"))
    OPENAI_BASE_URL: str = Field(
        default_factory=lambda: os.getenv("OPENAI_BASE_URL", "https://codecraftapi.com/v1")
    )
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
        default_factory=lambda: os.getenv("ORCHESTRATOR_MODEL", "gpt-5.5")
    )
    SUBAGENT_MODEL: str = Field(
        default_factory=lambda: os.getenv("SUBAGENT_MODEL", "gemini-3.7-flash")
    )
    JUDGE_MODEL: str = Field(
        default_factory=lambda: os.getenv("JUDGE_MODEL", "gpt-5.5-pro")
    )
    EMBEDDING_MODEL: str = Field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    )

    # Paths
    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    MENU_FILE_PATH: Path = DATA_DIR / "menu.json"
    BRANCHES_FILE_PATH: Path = DATA_DIR / "branches.json"
    PROMOS_FILE_PATH: Path = DATA_DIR / "promos.json"
    DB_PATH: Path = Field(
        default_factory=lambda: Path(os.getenv("DB_PATH", str(BASE_DIR / "data" / "orders.db")))
    )
    KB_PATH: Path = DATA_DIR / "knowledge"
    CHROMA_PATH: Path = DATA_DIR / "chroma"
    PROMPTS_DIR: Path = BASE_DIR / "app" / "agents" / "prompts"

    # Session & Redis
    REDIS_URL: str = Field(default_factory=lambda: os.getenv("REDIS_URL", ""))
    SESSION_TTL_SECONDS: int = 86400  # 24 hours
    DEDUPE_TTL_SECONDS: int = 600  # 10 minutes
    RATE_LIMIT_PER_MINUTE: int = Field(
        default_factory=lambda: int(os.getenv("RATE_LIMIT_PER_MINUTE", "20"))
    )
    
    # RAG Configuration
    KB_EXCLUDE_DIRS: List[str] = ["internal"]
    KB_EXCLUDE_FILES: List[str] = ["README.md"]
    RAG_TOP_K: int = 4  # Best chunks handed to the LLM after reranking
    RAG_DISTANCE_CUTOFF: float = 0.65  # Cosine distance cutoff (1.0 - cosine_sim), legacy helper

    # Ingestion: chunking (characters) and blue/green build retention
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 100
    MIN_CHUNK_SIZE: int = 40  # Sections shorter than this are just titles; skipped
    MAX_CHUNK_CHARS: int = 1600  # Pre-flight hard limit (context header + section)
    BUILDS_TO_KEEP: int = 2  # Newest build is live, the one before it is a backup
    INDEX_INFO_FILE: Path = DATA_DIR / "chroma" / "index_info.json"  # Manifest

    # Retrieval: hybrid search, reranking and relevance gate
    RAG_SEARCH_RESULTS: int = 20  # Candidates per search method before reranking
    MIN_RELEVANCE_SCORE: float = Field(
        default_factory=lambda: float(os.getenv("MIN_RELEVANCE_SCORE", "0.30"))
    )
    # Optional cross-encoder (needs sentence-transformers). Empty = built-in fusion reranker
    RERANKER_MODEL: str = Field(default_factory=lambda: os.getenv("RERANKER_MODEL", ""))
    RERANKER_MIN_SCORE: float = Field(
        default_factory=lambda: float(os.getenv("RERANKER_MIN_SCORE", "-9"))
    )

    # Search-time access control: role -> top-level KB folders it may search
    ROLE_ACCESS: Dict[str, List[str]] = {
        "customer": ["menu", "branches", "offers", "policies", "company", "faq"],
        "staff": ["menu", "branches", "offers", "policies", "company", "faq"],
        "manager": ["menu", "branches", "offers", "policies", "company", "faq", "internal"],
    }

    # Knowledge agent guards
    MAX_QUESTION_LENGTH: int = 1000
    MAX_HISTORY_MESSAGES: int = 10
    SHOW_CITATIONS: bool = Field(
        default_factory=lambda: os.getenv("SHOW_CITATIONS", "false").lower() == "true"
    )

    # Business Rules & State
    MIN_ORDER_LKR: int = 1500
    TIMEZONE: str = "Asia/Colombo"
    LOG_LEVEL: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    MAX_TOOL_ITERATIONS: int = 6

    # Phase 6: Voice Notes (STT & Optional TTS)
    STT_PROVIDER: str = Field(default_factory=lambda: os.getenv("STT_PROVIDER", "faster_whisper"))
    STT_MODEL: str = Field(default_factory=lambda: os.getenv("STT_MODEL", "small"))
    STT_CONFIDENCE_THRESHOLD: float = Field(
        default_factory=lambda: float(os.getenv("STT_CONFIDENCE_THRESHOLD", "0.75"))
    )
    MAX_AUDIO_SECONDS: float = Field(
        default_factory=lambda: float(os.getenv("MAX_AUDIO_SECONDS", "60.0"))
    )
    MAX_AUDIO_BYTES: int = Field(
        default_factory=lambda: int(os.getenv("MAX_AUDIO_BYTES", "2097152"))
    )
    TTS_ENABLED: bool = Field(
        default_factory=lambda: os.getenv("TTS_ENABLED", "false").lower() == "true"
    )
    TTS_PROVIDER: str = Field(default_factory=lambda: os.getenv("TTS_PROVIDER", "openai"))


settings = Settings()
