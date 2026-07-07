"""Per-farm scheduler run classification.

The non-flowmeter jobs (alert check, daily recommendations, data ingestion,
reference recompute) iterate every farm with a per-farm try/except. Before this,
they recorded the run as "success" even when every farm raised — a total outage
looked healthy on the scheduler_job_runs_total metric. classify_per_farm_run
distinguishes success / partial_failure / failure so alerting can fire.
"""

from app.services.scheduler import classify_per_farm_run


def test_all_farms_ok_is_success():
    assert classify_per_farm_run(farms_ok=5, farms_failed=0) == "success"


def test_no_farms_processed_is_success():
    # Empty install / nothing to do is not a failure.
    assert classify_per_farm_run(farms_ok=0, farms_failed=0) == "success"


def test_all_farms_failed_is_failure():
    assert classify_per_farm_run(farms_ok=0, farms_failed=4) == "failure"


def test_some_farms_failed_is_partial_failure():
    assert classify_per_farm_run(farms_ok=3, farms_failed=2) == "partial_failure"


def test_probe_calibration_job_is_registered():
    import asyncio

    from app.services.scheduler import start_scheduler, stop_scheduler

    async def _check() -> set[str]:
        sched = start_scheduler()
        try:
            return {j.id for j in sched.get_jobs()}
        finally:
            stop_scheduler()

    ids = asyncio.run(_check())
    assert "probe_calibration" in ids


async def test_start_scheduler_registers_all_expected_jobs():
    """Exact job-id set + the irrigation_fingerprint cron schedule.

    Guards against silent job-registration drift (a renamed/dropped add_job
    call would otherwise only surface in production as a missing job run).
    start_scheduler() calls _scheduler.start(), which needs a running event
    loop — this test is async (pytest-asyncio auto mode) so one exists.
    """
    from apscheduler.triggers.cron import CronTrigger

    from app.services import scheduler as scheduler_module
    from app.services.scheduler import start_scheduler

    scheduler_module._scheduler = None
    try:
        sched = start_scheduler()
        jobs = {j.id: j for j in sched.get_jobs()}
        assert set(jobs) == {
            "alert_check",
            "daily_recommendations",
            "data_ingestion",
            "flowmeter_ingestion",
            "reference_recompute",
            "probe_calibration",
            "irrigation_fingerprint",
        }

        fingerprint_trigger = jobs["irrigation_fingerprint"].trigger
        assert isinstance(fingerprint_trigger, CronTrigger)
        trigger_fields = {f.name: str(f) for f in fingerprint_trigger.fields}
        assert trigger_fields["day_of_week"] == "mon"
        assert trigger_fields["hour"] == "4"
        assert trigger_fields["minute"] == "30"
    finally:
        sched = scheduler_module._scheduler
        if sched is not None:
            sched.shutdown(wait=False)
        scheduler_module._scheduler = None
