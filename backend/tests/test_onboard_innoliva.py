from scripts.onboard_innoliva import (
    POLO_META, parse_variety, extract_soil_moisture_depths,
)


def test_polo_meta_covers_six_polos():
    assert set(POLO_META) == {
        "Conceição", "Covadonga", "Fátima", "Guadalupe", "Rocio", "Carmo",
    }
    assert POLO_META["Covadonga"] == ("167", "574")
    assert POLO_META["Conceição"] == ("170", None)


def test_parse_variety_from_parens_and_keywords():
    assert parse_variety("Herdade de Sousa UPC4 (Cobrançosa)") == "Cobrançosa"
    assert parse_variety("Herdade de Sousa UPC5 (Picoal)") == "Picoal"
    assert parse_variety("Bussalfão UPC1") is None


def test_extract_soil_moisture_depths_ignores_summed_and_dedups():
    raw = {"data": {"sensors": [
        {"id": "1", "sensor_type": "Soil Moisture", "name": "5 cm", "units": "vol %"},
        {"id": "2", "sensor_type": "Soil Moisture", "name": "15cm", "units": "vol %"},
        {"id": "3", "sensor_type": "Soil Moisture Summed", "name": "5 cm", "units": "mm"},
        {"id": "4", "sensor_type": "Soil Temperature", "name": "5 cm", "units": "ºC"},
    ]}}
    assert extract_soil_moisture_depths(raw) == [5, 15]
