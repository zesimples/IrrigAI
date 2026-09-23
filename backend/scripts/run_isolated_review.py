"""Run review checks against the dedicated disposable database, never development."""

import os
import runpy
import sys

import psycopg2
from sqlalchemy.engine import make_url

DATABASE = "irrigai_ai_review_20260921"


def main():
    command, *arguments = sys.argv[1:]
    if command not in {"pytest", "alembic", "seed", "live-eval"}:
        raise SystemExit("Expected pytest, alembic, seed or live-eval")
    for key in ("DATABASE_URL", "DATABASE_URL_SYNC"):
        os.environ[key] = (
            make_url(os.environ[key]).set(database=DATABASE).render_as_string(hide_password=False)
        )
    os.environ.update(
        LLM_PROVIDER="mock",
        PROBE_PROVIDER="mock",
        WEATHER_PROVIDER="mock",
        REDIS_URL="redis://irrigai-review-redis-20260921:6379/15",
        DEBUG="false",
    )
    if command == "live-eval":
        # Explicit opt-in: only the bounded synthetic/anonymised fixture suites.
        # Both DB URLs and Redis stay isolated, including autouse pytest cleanup.
        os.environ["LLM_PROVIDER"] = "openai"
        if arguments not in ([], ["chat"]):
            raise SystemExit("live-eval accepts only an optional 'chat' subset")
        suites = (
            ["tests/ai_eval/eval_chat_multiturn.py"]
            if arguments
            else ["tests/ai_eval/eval_golden_set.py", "tests/ai_eval/eval_chat_multiturn.py"]
        )
        arguments = [*suites, "-q", "-ra", "--tb=short"]
    url = make_url(os.environ["DATABASE_URL_SYNC"])
    async_url = make_url(os.environ["DATABASE_URL"])
    if (async_url.host, async_url.port, async_url.username, async_url.database) != (
        url.host,
        url.port,
        url.username,
        url.database,
    ):
        raise SystemExit("Database URLs do not identify the same isolated target")
    with (
        psycopg2.connect(
            host=url.host,
            port=url.port or 5432,
            user=url.username,
            password=url.password,
            dbname=DATABASE,
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database()")
        if cursor.fetchone()[0] != DATABASE:
            raise SystemExit("Wrong database: refusing review command")
    print(f"Verified isolated target for both database URLs: {DATABASE}", flush=True)
    if command in {"pytest", "live-eval"}:
        import pytest

        raise SystemExit(pytest.main(arguments))
    sys.argv = [command, *arguments]
    runpy.run_module("app.seed" if command == "seed" else "alembic", run_name="__main__")


if __name__ == "__main__":
    main()
