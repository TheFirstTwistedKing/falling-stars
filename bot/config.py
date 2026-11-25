"""환경 변수 설정. .env 파일이 있으면 읽는다."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "")
DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID", "0") or 0)
DB_PATH = os.getenv("DB_PATH", str(ROOT / "data" / "falling_stars.db"))
LORE_PATH = os.getenv("LORE_PATH", str(ROOT / "data" / "lore.json"))
GM_ROLE_NAME = os.getenv("GM_ROLE_NAME", "GM")
LOG_CHAT = os.getenv("LOG_CHAT", "false").lower() in ("1", "true", "yes")
