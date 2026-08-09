"""Settings loading from the environment."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from app.config import Settings, settings

ENV_VARS = [
    "AGENT_MODEL",
    "AGENT_MAX_ITERATIONS",
    "AGENT_MAX_TOKENS",
    "AGENT_EFFORT",
    "AGENT_WORKSPACE",
    "SERPER_API_KEY",
    "LOG_LEVEL",
]


@pytest.fixture
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_defaults(clean_env):
    s = Settings.from_env()
    assert s.model == "claude-opus-4-8"
    assert s.max_iterations == 20
    assert s.max_tokens == 16000
    assert s.effort == "high"
    assert s.workspace_root == Path("workspace").resolve()
    assert s.serper_api_key is None
    assert s.log_level == "INFO"


def test_every_value_comes_from_the_environment(clean_env, tmp_path):
    clean_env.setenv("AGENT_MODEL", "claude-sonnet-5")
    clean_env.setenv("AGENT_MAX_ITERATIONS", "3")
    clean_env.setenv("AGENT_MAX_TOKENS", "2048")
    clean_env.setenv("AGENT_EFFORT", "low")
    clean_env.setenv("AGENT_WORKSPACE", str(tmp_path / "ws"))
    clean_env.setenv("SERPER_API_KEY", "sk-serp")
    clean_env.setenv("LOG_LEVEL", "DEBUG")

    s = Settings.from_env()

    assert s.model == "claude-sonnet-5"
    assert s.max_iterations == 3
    assert s.max_tokens == 2048
    assert s.effort == "low"
    assert s.workspace_root == tmp_path / "ws"
    assert s.serper_api_key == "sk-serp"
    assert s.log_level == "DEBUG"


def test_workspace_root_is_absolute_even_when_relative(clean_env):
    clean_env.setenv("AGENT_WORKSPACE", "some/relative/dir")
    root = Settings.from_env().workspace_root
    assert root.is_absolute()
    assert root.parts[-3:] == ("some", "relative", "dir")


def test_workspace_root_normalises_traversal(clean_env, tmp_path):
    clean_env.setenv("AGENT_WORKSPACE", str(tmp_path / "a" / ".." / "b"))
    assert Settings.from_env().workspace_root == tmp_path / "b"


@pytest.mark.parametrize("var", ["AGENT_MAX_ITERATIONS", "AGENT_MAX_TOKENS"])
def test_non_numeric_int_settings_fail_loudly(clean_env, var):
    clean_env.setenv(var, "not-a-number")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_empty_serper_key_is_falsy(clean_env):
    """An exported-but-blank key must not enable the live search path."""
    clean_env.setenv("SERPER_API_KEY", "")
    assert not Settings.from_env().serper_api_key


def test_settings_are_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.model = "something-else"


def test_module_singleton_is_a_settings_instance():
    assert isinstance(settings, Settings)


def test_replace_produces_an_independent_copy():
    """`dataclasses.replace` is how tests override config; it must not mutate."""
    original = settings.max_iterations
    copy = dataclasses.replace(settings, max_iterations=original + 5)
    assert copy.max_iterations == original + 5
    assert settings.max_iterations == original
    assert copy.model == settings.model
