"""AI Shorts Generator backend package."""

from pathlib import Path

from dotenv import load_dotenv


# Load local development configuration before service modules create their
# environment-backed singleton instances. Existing process variables win so
# Docker, CI, and production deployments can override backend/.env safely.
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
