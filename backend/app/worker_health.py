"""Worker liveness probe — used as the Docker healthcheck for the worker service.

Exits 0 when the scheduler heartbeat is fresh, non-zero otherwise (no heartbeat
yet, stale heartbeat, or Redis unreachable). Run as ``python -m app.worker_health``.
"""

from __future__ import annotations

import sys

from app.heartbeat import STALE_THRESHOLD_SECONDS, heartbeat_age_seconds


def main() -> int:
    try:
        age = heartbeat_age_seconds()
    except Exception as exc:  # Redis unreachable
        print(f"worker unhealthy: heartbeat check failed: {exc}")
        return 1
    if age is None:
        print("worker unhealthy: no scheduler heartbeat recorded yet")
        return 1
    if age > STALE_THRESHOLD_SECONDS:
        print(f"worker unhealthy: scheduler heartbeat is stale ({age:.0f}s old)")
        return 1
    print(f"worker healthy: scheduler heartbeat {age:.0f}s old")
    return 0


if __name__ == "__main__":
    sys.exit(main())
