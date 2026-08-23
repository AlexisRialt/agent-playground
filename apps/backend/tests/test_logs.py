"""Logging setup, the per-job binding, and the `short()` preview helper."""

from __future__ import annotations

import logging
import sys

import pytest
from loguru import logger

from app import logs
from app.logs import _InterceptHandler, job_logger, setup_logging, short


@pytest.fixture
def captured():
    """Swap loguru's sinks for an in-memory list, then restore the originals."""
    lines: list[str] = []

    def format_like_production(record) -> str:
        # `_formatter` is what populates `extra[job_tag]`; reuse it so the
        # per-job tagging is exercised for real, minus the colours and clock.
        logs._formatter(record)
        return "{extra[job_tag]}{message}\n"

    logger.remove()
    sink_id = logger.add(
        lambda message: lines.append(message.rstrip("\n")),
        level="DEBUG",
        format=format_like_production,
    )
    yield lines
    logger.remove(sink_id)
    logger.add(sys.stdout, level="DEBUG")


@pytest.fixture
def unconfigured(monkeypatch):
    """Pretend `setup_logging` has never run, and restore sinks afterwards."""
    monkeypatch.setattr(logs, "_configured", False)
    root_handlers = logging.root.handlers[:]
    root_level = logging.root.level
    yield
    logger.remove()
    logger.add(sys.stdout, level="DEBUG")
    logging.root.handlers[:] = root_handlers
    logging.root.setLevel(root_level)


# --------------------------------------------------------------------------
# short()
# --------------------------------------------------------------------------


def test_short_passes_through_a_simple_string():
    assert short("hello world") == "hello world"


def test_short_collapses_all_whitespace_to_single_spaces():
    assert short("a\n\n  b\tc \r\n d") == "a b c d"


def test_short_strips_leading_and_trailing_whitespace():
    assert short("  padded  ") == "padded"


def test_short_truncates_and_reports_the_overflow():
    assert short("x" * 105, 100) == "x" * 100 + "… (+5 chars)"


def test_short_leaves_text_exactly_at_the_limit_alone():
    assert short("x" * 100, 100) == "x" * 100


def test_short_truncates_one_character_over_the_limit():
    assert short("x" * 101, 100).endswith("… (+1 chars)")


def test_short_defaults_to_a_300_character_limit():
    assert short("y" * 301).endswith("… (+1 chars)")


def test_short_accepts_non_strings():
    assert short({"command": "list", "path": "."}) == "{'command': 'list', 'path': '.'}"
    assert short(None) == "None"
    assert short(42) == "42"


def test_short_of_empty_input():
    assert short("") == ""
    assert short("   \n  ") == ""


def test_short_output_is_always_single_line():
    assert "\n" not in short("line one\nline two\nline three")


# --------------------------------------------------------------------------
# job_logger / the per-job tag
# --------------------------------------------------------------------------


def test_job_logger_tags_lines_with_the_short_job_id(captured):
    job_logger("abcdef0123456789abcdef0123456789").info("working")
    assert captured == ["[abcdef01] working"]


def test_plain_logger_lines_are_untagged(captured):
    logger.info("no job here")
    assert captured == ["no job here"]


def test_job_loggers_do_not_leak_into_each_other(captured):
    job_logger("1" * 32).info("first")
    job_logger("2" * 32).info("second")
    logger.info("third")
    assert captured == ["[11111111] first", "[22222222] second", "third"]


def test_formatter_builds_the_tag_and_returns_a_format_string():
    record = {"extra": {"job_id": "0123456789abcdef"}}
    template = logs._formatter(record)
    assert record["extra"]["job_tag"] == "[01234567] "
    assert "{extra[job_tag]}" in template
    assert template.endswith("\n{exception}")


def test_formatter_leaves_the_tag_empty_without_a_job_id():
    record = {"extra": {}}
    logs._formatter(record)
    assert record["extra"]["job_tag"] == ""


def test_formatter_handles_a_short_job_id():
    record = {"extra": {"job_id": "abc"}}
    logs._formatter(record)
    assert record["extra"]["job_tag"] == "[abc] "


# --------------------------------------------------------------------------
# setup_logging
# --------------------------------------------------------------------------


def test_setup_logging_installs_a_stdout_sink(unconfigured, capsys):
    setup_logging("INFO")
    logger.info("hello from loguru")
    assert "hello from loguru" in capsys.readouterr().out


def test_setup_logging_honours_the_level(unconfigured, capsys):
    setup_logging("WARNING")
    logger.info("suppressed")
    logger.warning("shown")
    out = capsys.readouterr().out
    assert "suppressed" not in out
    assert "shown" in out


def test_setup_logging_accepts_a_lowercase_level(unconfigured, capsys):
    setup_logging("debug")
    logger.debug("debug line")
    assert "debug line" in capsys.readouterr().out


def test_setup_logging_is_idempotent(unconfigured, capsys):
    setup_logging("INFO")
    setup_logging("INFO")  # a second sink would duplicate every line
    logger.info("only once")
    assert capsys.readouterr().out.count("only once") == 1


def test_setup_logging_marks_itself_configured(unconfigured):
    setup_logging("INFO")
    assert logs._configured is True


def test_stdlib_logging_is_routed_into_loguru(unconfigured, capsys):
    setup_logging("INFO")
    logging.getLogger("uvicorn.access").info("GET /healthz 200")
    out = capsys.readouterr().out
    assert "GET /healthz 200" in out
    assert "uvicorn.access" in out


def test_noisy_third_party_loggers_are_turned_down(unconfigured, capsys):
    setup_logging("DEBUG")
    logging.getLogger("httpcore").info("connection details")
    logging.getLogger("httpx").info("HTTP Request: GET https://example")
    out = capsys.readouterr().out
    assert "connection details" not in out
    assert "HTTP Request" in out


# --------------------------------------------------------------------------
# _InterceptHandler
# --------------------------------------------------------------------------


def make_record(level: int, message: str, name: str = "some.lib") -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


def test_intercept_handler_forwards_the_message(captured):
    _InterceptHandler().emit(make_record(logging.WARNING, "careful"))
    assert captured == ["careful"]


def test_intercept_handler_formats_percent_style_args(captured):
    record = logging.LogRecord(
        name="lib",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="took %d ms",
        args=(12,),
        exc_info=None,
    )
    _InterceptHandler().emit(record)
    assert captured == ["took 12 ms"]


def test_intercept_handler_falls_back_to_the_numeric_level(captured):
    """Custom stdlib levels have no loguru name; the number must still work."""
    logging.addLevelName(25, "NOTICE")
    _InterceptHandler().emit(make_record(25, "custom level"))
    assert captured == ["custom level"]


def test_intercept_handler_does_not_crash_on_exception_info(captured):
    try:
        raise ValueError("inner")
    except ValueError:
        record = logging.LogRecord(
            name="lib",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )
    _InterceptHandler().emit(record)
    assert captured[0].startswith("failed")
