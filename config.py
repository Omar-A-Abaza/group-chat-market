import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-insecure-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.environ.get(
        "DATABASE_PATH", str(BASE_DIR / "instance" / "market.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # Per-group settings
    GROUP_NAME = os.environ.get("GROUP_NAME", "Group Chat Market")
    START_CASH = _float("START_CASH", 1000)
    DEFAULT_B = _float("DEFAULT_B", 250)
    # Login rate limiting: this many failures per window locks the (ip, username) pair.
    LOGIN_MAX_FAILURES = 5
    LOGIN_WINDOW_SECONDS = 600
