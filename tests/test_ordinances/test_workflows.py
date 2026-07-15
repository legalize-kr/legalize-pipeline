"""Workflow coverage for ordinance history cache and daily updates."""

from pathlib import Path

import yaml


def test_daily_cache_refresh_resumes_bounded_ordinance_history_backfill():
    text = Path(".github/workflows/daily-cache-refresh.yml").read_text(encoding="utf-8")

    yaml.compose(text)
    assert "timeout-minutes: 600" in text
    assert "LEGALIZE_CACHE_DIR: ${{ secrets.LEGALIZE_CACHE_DIR }}" in text
    assert text.index("Link persistent cache") < text.index("Fetch ordinances cache")
    workflow = yaml.load(text, Loader=yaml.BaseLoader)
    assert workflow["env"]["LAW_API_DAILY_BUDGET"] == "300000"
    assert workflow["env"]["ORDINANCE_MAX_NEW_DETAILS"] == (
        "${{ inputs.ordinance_max_new_details || '50000' }}"
    )
    ordinance_input = workflow["on"]["workflow_dispatch"]["inputs"][
        "ordinance_max_new_details"
    ]
    assert ordinance_input["default"] == "50000"
    assert (
        'python -m ordinances.fetch_cache --history --display 500 --max-new-details "$ORDINANCE_MAX_NEW_DETAILS"'
        in text
    )
    for step_id in ("fetch_laws", "fetch_precedents", "fetch_admrules", "fetch_ordinances"):
        assert f"id: {step_id}\n        continue-on-error: true" in text
        assert f"steps.{step_id}.outcome" in text
    assert "name: Report cache fetch failures" in text
    assert 'python -m cache.baseline --cache-dir "$LEGALIZE_CACHE_DIR" --output cache-baseline.json' in text
    assert "path: ${{ env.PIPELINE_REPO }}/cache-baseline.json" in text
    gate = text.index("python -m cache.baseline")
    upload = text.index("name: Upload baseline artifact")
    report = text.index("name: Report cache fetch failures")
    assert gate < upload < report


def test_daily_ordinance_update_still_updates_validates_and_pushes():
    text = Path(".github/workflows/daily-ordinance-update.yml").read_text(encoding="utf-8")

    yaml.compose(text)
    assert "fetch-depth: 0" in text
    update = text.index("python -m ordinances.update")
    validate = text.index("python -m ordinances.validate")
    push = text.index("git push")
    assert update < validate < push
    assert "--days 14 --commit" in text
    assert "git log origin/main..HEAD --oneline" in text


def test_weekly_cache_release_includes_nested_ordinance_history():
    text = Path(".github/workflows/weekly-cache-release.yml").read_text(encoding="utf-8")

    yaml.compose(text)
    assert "-C .cache detail history precedent images admrule ordinance" in text


def test_daily_laws_update_has_time_for_existing_backfill_and_audits():
    text = Path(".github/workflows/daily-laws-update.yml").read_text(encoding="utf-8")

    yaml.compose(text)
    assert "timeout-minutes: 360" in text
    update = text.index("python -m laws.update --days 14 --backfill-missing-from-cache")
    validate = text.index("python -m laws.validate")
    cache_audit = text.index("python -m laws.audit_cache_vs_repo")
    history_audit = text.index("python -m laws.audit_history_vs_git")
    push = text.index("git push")
    assert update < validate < cache_audit < history_audit < push
