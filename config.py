import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-insecure-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.environ.get(
        "DATABASE_PATH", str(BASE_DIR / "instance" / "group_chat_market.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    START_CASH = 1000.0
    DEFAULT_B = 250.0
