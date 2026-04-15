"""Delta-gate helper for the daily-laws-update CI step.

Encapsulates the Python block that was previously inlined as a heredoc in
``daily-laws-update.yml`` ("Report import failures" step).  Extracting it
here makes the logic directly unit-testable without subprocess round-trips.

Public API
----------
evaluate_delta(cur, base, now_ts) -> tuple[int, list[str]]
    Analyse the delta between the current failure state and the baseline.

    Parameters
    ----------
    cur : dict
        Parsed ``.failed_msts.json`` (keys: ``failed_msts``, ``search_misses``).
    base : dict
        Parsed ``pipeline/.failure-baseline.json`` (same shape; may be empty /
        missing — callers pass ``{}`` for the not-found case).
    now_ts : float
        Current UNIX timestamp (``time.time()``).  Injected for testability.

    Returns
    -------
    (exit_code, messages) where:
    - exit_code == 0  →  job should pass
    - exit_code == 1  →  job should fail
    - messages        →  list of human-readable lines (notice / warning / error)
"""

from __future__ import annotations

TRANSIENT_REASONS: frozenset[str] = frozenset({"api_error"})
TRANSIENT_GRACE_SEC: float = 24 * 3600


def _empty_state() -> dict:
    return {"failed_msts": {}, "search_misses": {}}


def evaluate_delta(
    cur: dict,
    base: dict,
    now_ts: float,
) -> tuple[int, list[str]]:
    """Return ``(exit_code, messages)`` from comparing *cur* against *base*."""
    cur = {**_empty_state(), **cur}
    base = {**_empty_state(), **base}

    cur_tuples = {(m, e.get("reason", "")) for m, e in cur["failed_msts"].items()}
    base_tuples = {(m, e.get("reason", "")) for m, e in base["failed_msts"].items()}
    delta = cur_tuples - base_tuples

    semantic: list[tuple[str, str]] = []
    transient: list[tuple[str, str]] = []
    for mst, reason in delta:
        entry = cur["failed_msts"].get(mst, {})
        failed_at = entry.get("failed_at", 0)
        age = now_ts - failed_at if failed_at else float("inf")
        if reason in TRANSIENT_REASONS and age <= TRANSIENT_GRACE_SEC:
            transient.append((mst, reason))
        else:
            semantic.append((mst, reason))

    new_misses = set(cur["search_misses"]) - set(base["search_misses"])

    messages: list[str] = []
    messages.append(
        f"::notice::failed_msts_total={len(cur['failed_msts'])} "
        f"delta_semantic={len(semantic)} delta_transient={len(transient)}"
    )
    messages.append(
        f"::notice::search_misses_total={len(cur['search_misses'])} new={len(new_misses)}"
    )

    if transient and not semantic and not new_misses:
        messages.append(
            f"::warning::transient api_error within 24h grace: "
            f"{sorted(transient)[:20]} — not failing the job"
        )

    if semantic or new_misses:
        messages.append(
            f"::error::new failures detected: "
            f"semantic={sorted(semantic)[:20]} new_misses={sorted(new_misses)[:20]}"
        )
        return 1, messages

    return 0, messages


def _load_json(path: str) -> dict:
    import json
    import os

    if not os.path.exists(path):
        return _empty_state()
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    """CLI entrypoint for CI: reads ``.failed_msts.json`` and the baseline,
    prints messages, and returns an exit code.

    Paths are relative to the current working directory (CI sets
    ``working-directory: workspace`` so ``.failed_msts.json`` is at the data-repo
    root and ``pipeline/.failure-baseline.json`` is the sibling pipeline repo).
    """
    import time

    cur = _load_json(".failed_msts.json")
    base = _load_json("pipeline/.failure-baseline.json")
    code, messages = evaluate_delta(cur, base, time.time())
    for m in messages:
        print(m)
    return code


if __name__ == "__main__":
    import sys

    sys.exit(main())
