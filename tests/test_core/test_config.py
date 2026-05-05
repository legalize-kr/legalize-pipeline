"""Tests for shared workspace path configuration."""

from core import config


def test_default_workspace_is_meta_root():
    assert config.WORKSPACE_ROOT == config.PROJECT_ROOT.parent


def test_default_repo_paths_are_workspace_children():
    assert config.LEGALIZE_KR_REPO == config.WORKSPACE_ROOT / "legalize-kr"
    assert config.PRECEDENT_KR_REPO == config.WORKSPACE_ROOT / "precedent-kr"
    assert config.ADMRULE_KR_REPO == config.WORKSPACE_ROOT / "admrule-kr"
    assert config.ORDINANCE_KR_REPO == config.WORKSPACE_ROOT / "ordinance-kr"
    assert config.CACHE_ROOT == config.WORKSPACE_ROOT / ".cache"
