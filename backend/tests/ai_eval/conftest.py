"""Per-case measurements for the opt-in live evaluation.

A pass count hides what the A4 gate must report separately: repairs, fallbacks,
failures, skips, latency and tokens. Each case is timed, and its token use is read
as the delta of the OpenAI client's own Prometheus counters, so nothing in product
code changes in order to be measured. Set AI_EVAL_REPORT to write the JSON report.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter

import pytest

from app.metrics import ai_tokens_input_total, ai_tokens_output_total

_RESULTS: list[dict] = []
_OUTCOME = pytest.StashKey[str]()


def _tokens() -> tuple[float, float]:
    def total(counter) -> float:
        return sum(
            sample.value
            for metric in counter.collect()
            for sample in metric.samples
            if sample.name.endswith("_total")
        )

    return total(ai_tokens_input_total), total(ai_tokens_output_total)


@pytest.fixture(autouse=True)
def _measure_case(record_property):
    tokens_in, tokens_out = _tokens()
    started = time.perf_counter()
    yield
    after_in, after_out = _tokens()
    record_property("duration_s", round(time.perf_counter() - started, 2))
    record_property("tokens_in", int(after_in - tokens_in))
    record_property("tokens_out", int(after_out - tokens_out))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    report = (yield).get_result()
    # The outcome is decided in setup (a skip) or the call phase, but the fixture
    # above records duration and tokens in its teardown, after the call report —
    # so the row is written at teardown with the outcome carried forward.
    if report.when == "call" or (report.when == "setup" and report.skipped):
        item.stash[_OUTCOME] = report.outcome
    if report.when == "teardown":
        _RESULTS.append(
            {
                "case": item.callspec.id if hasattr(item, "callspec") else item.name,
                "suite": item.module.__name__.rsplit(".", 1)[-1],
                "outcome": item.stash.get(_OUTCOME, "error"),
                **dict(item.user_properties),
            }
        )


def pytest_terminal_summary(terminalreporter):
    if not _RESULTS:
        return
    outcomes = Counter(row["outcome"] for row in _RESULTS)
    turns = Counter(status for row in _RESULTS for status in row.get("turn_statuses", []))
    degraded = sum(1 for row in _RESULTS if row.get("degraded"))
    tokens_in = sum(row.get("tokens_in", 0) for row in _RESULTS)
    tokens_out = sum(row.get("tokens_out", 0) for row in _RESULTS)
    durations = sorted(row["duration_s"] for row in _RESULTS if "duration_s" in row)
    terminalreporter.section("A4 live-evaluation measurements")
    terminalreporter.line(f"cases: {dict(outcomes)}")
    terminalreporter.line(f"chat turns by validation status: {dict(turns)}")
    terminalreporter.line(f"structured cases marked degraded: {degraded}")
    terminalreporter.line(f"tokens: input {tokens_in}, output {tokens_out}")
    if durations:
        median = durations[len(durations) // 2]
        terminalreporter.line(f"case duration s: median {median}, max {durations[-1]}")
    path = os.environ.get("AI_EVAL_REPORT")
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(_RESULTS, handle, ensure_ascii=False, indent=2)
        terminalreporter.line(f"report written to {path}")
