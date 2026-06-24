from app.models import ProbeCalibration


def test_probe_calibration_table_registered():
    assert ProbeCalibration.__tablename__ == "probe_calibration"
    cols = set(ProbeCalibration.__table__.columns.keys())
    assert {
        "id", "sector_id", "observed_fc", "observed_refill",
        "method", "num_cycles", "consistency", "window_days", "computed_at",
    } <= cols
