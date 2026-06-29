# config.py — X (Twitter) AI Daily Tweet Automation
import os
from pathlib import Path
from dotenv import load_dotenv

_ENV_PATH = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)

GROQ_API_KEY          = os.getenv("GROQ_API_KEY", "")
TAVILY_API_KEY        = os.getenv("TAVILY_API_KEY", "")
POLLINATIONS_API_KEY  = os.getenv("POLLINATIONS_API_KEY", "")
# ── X (Twitter) Login — used by Playwright browser automation ────────────────
X_USERNAME   = os.getenv("X_USERNAME", "")
X_PASSWORD   = os.getenv("X_PASSWORD", "")
X_EMAIL      = os.getenv("X_EMAIL", "")
GOOGLE_SHEET_ID         = os.getenv("GOOGLE_SHEET_ID", "")
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials/service-account.json")
SHEET_NAME              = os.getenv("SHEET_NAME", "Tweets")
GMAIL_SENDER       = os.getenv("GMAIL_SENDER", "")
GMAIL_RECEIVER     = os.getenv("GMAIL_RECEIVER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
POST_TIME         = os.getenv("POST_TIME", "10:00")
MAX_RETRIES       = int(os.getenv("MAX_RETRIES", "3"))
QUALITY_MIN_SCORE = int(os.getenv("QUALITY_MIN_SCORE", "6"))

def _validate():
    critical = {
        "GROQ_API_KEY":         GROQ_API_KEY,
        "TAVILY_API_KEY":       TAVILY_API_KEY,
        "POLLINATIONS_API_KEY": POLLINATIONS_API_KEY,
        "X_USERNAME":           X_USERNAME,
        "X_PASSWORD":           X_PASSWORD,
        "GOOGLE_SHEET_ID":      GOOGLE_SHEET_ID,
        "GMAIL_SENDER":         GMAIL_SENDER,
        "GMAIL_RECEIVER":       GMAIL_RECEIVER,
        "GMAIL_APP_PASSWORD":   GMAIL_APP_PASSWORD,
    }
    missing = [k for k, v in critical.items() if not v]
    if missing:
        raise ValueError(
            "\n\n❌ Missing required environment variables (check your .env):\n"
            + "\n".join(f"  • {k}" for k in missing)
        )

_validate()
