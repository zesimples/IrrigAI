"""Unit tests for flowmeter ingestion run classification.

Regression context: `_run_flowmeter_ingestion` recorded the scheduler metric as
"success" whenever the job didn't raise — even when every device POST returned
406 "Client Signature Invalid" and zero readings were ingested. That masked a
two-day outage. classify_flowmeter_run() makes the all-failed case observable.
"""

from app.services.flowmeter_ingestion import classify_flowmeter_run


def test_all_devices_failed_and_nothing_inserted_is_failure():
    assert classify_flowmeter_run(readings_inserted=0, devices_failed=12) == "failure"


def test_partial_success_is_success():
    # Some devices ingested despite a failure elsewhere — the job did real work.
    assert classify_flowmeter_run(readings_inserted=5, devices_failed=3) == "success"


def test_clean_run_is_success():
    assert classify_flowmeter_run(readings_inserted=100, devices_failed=0) == "success"


def test_no_devices_processed_is_success():
    # Nothing to do (no active flowmeters / mock provider) is not a failure.
    assert classify_flowmeter_run(readings_inserted=0, devices_failed=0) == "success"
