from core.github_actions import report_partial_fetch


def test_report_partial_fetch_writes_warning_and_summary(tmp_path, monkeypatch, capsys):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    report_partial_fetch("Administrative rules", {"fetch_errors": 3})

    output = capsys.readouterr().out
    summary = summary_path.read_text(encoding="utf-8")
    assert "::warning title=Partial cache fetch::" in output
    assert "3 unclassified fetch error(s)" in output
    assert "### Administrative rules partial cache fetch" in summary
    assert "- Unclassified fetch errors: 3" in summary
    assert "Check for recurrence before adding an allowlist entry." in summary


def test_report_partial_fetch_is_silent_without_errors(tmp_path, monkeypatch, capsys):
    summary_path = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_path))

    report_partial_fetch("Ordinances", {"fetch_errors": 0})

    assert capsys.readouterr().out == ""
    assert not summary_path.exists()
