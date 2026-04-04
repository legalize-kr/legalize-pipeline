"""Shared HTTP request with throttle, retry, and exponential backoff."""

import logging
import time

import requests

from .throttle import Throttle

logger = logging.getLogger(__name__)


def make_request(
    url: str,
    params: dict,
    *,
    throttle: Throttle,
    api_key: str,
    max_retries: int = 3,
    backoff_base: float = 2.0,
) -> requests.Response:
    """Make a throttled HTTP GET with retry and exponential backoff."""
    params["OC"] = api_key

    for attempt in range(max_retries + 1):
        throttle.wait()
        try:
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                wait = backoff_base * (2 ** attempt)
                logger.warning(f"Rate limited (429). Waiting {wait}s before retry.")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt == max_retries:
                raise
            wait = backoff_base * (2 ** attempt)
            logger.warning(f"Request failed: {e}. Retry {attempt + 1}/{max_retries} in {wait}s")
            time.sleep(wait)

    raise RuntimeError(f"Exceeded {max_retries} retries for {url}")
