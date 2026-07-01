from app.models import FarmCredentials


def test_farm_credentials_has_project_id_column():
    fc = FarmCredentials(farm_id="00000000-0000-0000-0000-000000000000", project_id="170")
    assert fc.project_id == "170"
    assert "project_id" in FarmCredentials.__table__.columns
