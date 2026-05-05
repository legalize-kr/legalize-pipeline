"""Shared configuration for all pipelines."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", str(PROJECT_ROOT.parent))).resolve()
CACHE_ROOT = Path(os.environ.get("LEGALIZE_CACHE_DIR", str(WORKSPACE_ROOT / ".cache"))).resolve()
LEGALIZE_KR_REPO = Path(os.environ.get("LEGALIZE_KR_REPO", str(WORKSPACE_ROOT / "legalize-kr"))).resolve()
PRECEDENT_KR_REPO = Path(os.environ.get("PRECEDENT_KR_REPO", str(WORKSPACE_ROOT / "precedent-kr"))).resolve()
ADMRULE_KR_REPO = Path(os.environ.get("ADMRULE_KR_REPO", str(WORKSPACE_ROOT / "admrule-kr"))).resolve()
ORDINANCE_KR_REPO = Path(os.environ.get("ORDINANCE_KR_REPO", str(WORKSPACE_ROOT / "ordinance-kr"))).resolve()
LEGALIZE_WEB_REPO = Path(os.environ.get("LEGALIZE_WEB_REPO", str(WORKSPACE_ROOT / "legalize-web"))).resolve()
COMPILER_REPO = Path(os.environ.get("COMPILER_REPO", str(WORKSPACE_ROOT / "compiler"))).resolve()

# API
LAW_API_BASE = "http://www.law.go.kr/DRF"
LAW_API_KEY = os.environ.get("LAW_OC", os.environ.get("LAW_API_KEY", ""))

# Rate limiting
REQUEST_DELAY_SECONDS = 0.05
MAX_RETRIES = 5
BACKOFF_BASE_SECONDS = 3.0
CONCURRENT_WORKERS = 20

# Bot identity for automated commits
BOT_AUTHOR = "legalize-kr-bot <bot@legalize.kr>"
