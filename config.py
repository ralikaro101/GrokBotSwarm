import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
DISCORD_PREFIX = os.getenv("DISCORD_PREFIX", "!").strip() or "!"
MT5_BRIDGE_URL = os.getenv("MT5_BRIDGE_URL", "").strip()
MT5_BRIDGE_TOKEN = os.getenv("MT5_BRIDGE_TOKEN", "").strip()
