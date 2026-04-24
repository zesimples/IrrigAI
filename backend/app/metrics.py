"""Prometheus metrics registry for IrrigAI.

All counters/histograms are defined here so every module imports from one place.
The /metrics endpoint is mounted in main.py via prometheus_client.make_asgi_app().
"""

from prometheus_client import Counter, Histogram, Info

# ── HTTP ──────────────────────────────────────────────────────────────────────

http_requests_total = Counter(
    "irrigai_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)

http_request_duration_seconds = Histogram(
    "irrigai_http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

# ── Recommendations ───────────────────────────────────────────────────────────

recommendations_generated_total = Counter(
    "irrigai_recommendations_generated_total",
    "Recommendation generation attempts",
    ["action", "status"],  # status: success | failure
)

# ── Scheduler jobs ────────────────────────────────────────────────────────────

scheduler_job_runs_total = Counter(
    "irrigai_scheduler_job_runs_total",
    "Scheduler job execution attempts",
    ["job", "status"],  # status: success | failure | skipped
)

# ── AI / LLM ─────────────────────────────────────────────────────────────────

ai_requests_total = Counter(
    "irrigai_ai_requests_total",
    "LLM API calls",
    ["provider", "model", "status"],
)

ai_tokens_input_total = Counter(
    "irrigai_ai_tokens_input_total",
    "Total input tokens sent to LLM",
    ["provider", "model"],
)

ai_tokens_output_total = Counter(
    "irrigai_ai_tokens_output_total",
    "Total output tokens received from LLM",
    ["provider", "model"],
)

# ── System ────────────────────────────────────────────────────────────────────

app_info = Info("irrigai_app", "IrrigAI application metadata")
app_info.info({"version": "0.1.0"})
