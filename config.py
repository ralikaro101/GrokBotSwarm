import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
DISCORD_PREFIX = os.getenv("DISCORD_PREFIX", "!").strip() or "!"
