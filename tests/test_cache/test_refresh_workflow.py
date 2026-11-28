"""Execute refresh workflow steps with controlled disk and fetch results."""

import os
import subprocess
from pathlib import Path

import pytest
import yaml


def refresh_steps():
    workflow = yaml.load(
        Path('.github/workflows/daily-cache-refresh.yml').read_text(encoding='utf-8'),
        Loader=yaml.BaseLoader,
    )
    return workflow['jobs']['refresh']['steps']


def test_admrule_refresh_uses_published_history():
    steps = refresh_steps()
    checkout = next(step['with'] for step in steps
                    if step.get('with', {}).get('repository') == 'legalize-kr/admrule-kr')
    assert checkout['fetch-depth'] == '0'
    fetch = next(step for step in steps if step.get('id') == 'fetch_admrules')
    assert f'--published-repo "$GITHUB_WORKSPACE/{checkout["path"]}"' in fetch['run']


@pytest.mark.parametrize('cache_exists,available,expected', [
    (False, 20_000_000_000, 1),
    (False, 24_999_999_999, 1),
    (False, 25_000_000_000, 0),
    (True, 999_999_999, 1),
    (True, 1_000_000_000, 0),
    (True, 20_000_000_000, 0),
])
def test_preflight_checks_cache_filesystem(tmp_path, cache_exists, available, expected):
    steps = refresh_steps()
    names = [step.get('name') for step in steps]
    assert names.index('Disk preflight') < names.index('Link persistent cache')
    step = steps[names.index('Disk preflight')]
    cache = tmp_path / 'new parent' / 'persistent cache'
    if cache_exists:
        cache.mkdir(parents=True)
    df = tmp_path / 'df'
    df.write_text(
        '#!/bin/bash\n'
        '[[ "${@: -1}" == "$EXPECTED_DISK_PATH" ]] || exit 2\n'
        'if [[ "$*" == *"--output=avail"* ]]; then\n'
        f'  printf "Avail\\n{available}\\n"\n'
        'fi\n',
        encoding='utf-8',
    )
    df.chmod(0o755)
    result = subprocess.run(
        ['bash', '-eo', 'pipefail', '-c', step['run']],
        cwd=tmp_path,
        env={**os.environ, 'PATH': f'{tmp_path}:{os.environ["PATH"]}',
             'LEGALIZE_CACHE_DIR': str(cache),
             'EXPECTED_DISK_PATH': str(cache if cache_exists else tmp_path)},
        capture_output=True, text=True,
    )
    assert result.returncode == expected
    assert cache.exists() == cache_exists
    if expected:
        assert '::error::Insufficient disk' in result.stdout
        assert str(available) in result.stdout
        assert str(1_000_000_000 if cache_exists else 25_000_000_000) in result.stdout


@pytest.mark.parametrize('outcome', ['success', 'skipped', 'cancelled', 'failure'])
@pytest.mark.parametrize('fetch', ['laws', 'precedents', 'admrules', 'ordinances'])
def test_report_only_marks_actual_fetch_failures(tmp_path, outcome, fetch):
    step = next(step for step in refresh_steps()
                if step.get('name') == 'Report cache fetch failures')
    script = step['run']
    for name in ('laws', 'precedents', 'admrules', 'ordinances'):
        script = script.replace(
            '${{ steps.fetch_' + name + '.outcome }}',
            outcome if name == fetch else 'success',
        )
    summary = tmp_path / 'summary.md'
    result = subprocess.run(
        ['bash', '-eo', 'pipefail', '-c', script], cwd=tmp_path,
        env={**os.environ, 'GITHUB_STEP_SUMMARY': str(summary)},
        capture_output=True, text=True,
    )
    assert result.returncode == (1 if outcome == 'failure' else 0)
    assert result.stdout.count('::error::') == (1 if outcome == 'failure' else 0)
    report = summary.read_text(encoding='utf-8')
    for name in ('laws', 'precedents', 'admrules', 'ordinances'):
        assert f'- {name}: {outcome if name == fetch else "success"}' in report
    assert 'before continue-on-error' in report
