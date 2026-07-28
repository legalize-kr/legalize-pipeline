"""GitHub Actions reporting helpers."""

import os
from pathlib import Path


def report_partial_fetch(dataset: str, stats: dict[str, int]) -> None:
    """Report unclassified fetch errors without blocking successful imports."""
    errors = stats.get("fetch_errors", 0)
    if not errors:
        return

    message = (
        f"{dataset} update completed with {errors} unclassified fetch error(s); "
        "successful cached entries were still imported. "
        "Check for recurrence before adding an allowlist entry."
    )
    print(f"::warning title=Partial cache fetch::{message}")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary:
            summary.write(
                f"### {dataset} partial cache fetch\n\n"
                f"- Unclassified fetch errors: {errors}\n"
                "- Successful cached entries were still imported.\n"
                "- Check for recurrence before adding an allowlist entry.\n\n"
            )
