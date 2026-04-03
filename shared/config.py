"""Shared configuration for all pipelines."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", str(PROJECT_ROOT.parent)))

# API
LAW_API_BASE = "http://www.law.go.kr/DRF"
LAW_API_KEY = os.environ.get("LAW_OC", os.environ.get("LAW_API_KEY", ""))

# Rate limiting
REQUEST_DELAY_SECONDS = 0.2
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0
CONCURRENT_WORKERS = 5

# Bot identity for automated commits
BOT_AUTHOR = "legalize-kr-bot <bot@legalize.kr>"
