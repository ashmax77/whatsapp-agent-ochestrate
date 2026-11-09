import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
env_file = BASE_DIR / ".env"

if env_file.exists():
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())
    except Exception:
        pass

class Settings:
    PROJECT_NAME: str = "Pizza Agent Brain"
    OPENAI_API_KEY: str = os.getenv("OPENAI_KEY", "")
    DATA_DIR: Path = BASE_DIR / "data"
    MENU_FILE_PATH: Path = DATA_DIR / "menu.json"
    KNOWLEDGE_DIR: Path = DATA_DIR / "knowledge"

settings = Settings()
