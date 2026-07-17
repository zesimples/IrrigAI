"""Portuguese decimal formatting in user-facing engine/alert strings.

The UI language is pt-PT, so decimal values rendered into PT text must use
the comma separator ("7,8 mm"), never the English dot ("7.8 mm").
"""

from types import SimpleNamespace

from app.utils.format_pt import fmt_pt


class TestFmtPt:
    def test_one_decimal_uses_comma(self):
        assert fmt_pt(7.8, 1) == "7,8"

    def test_zero_decimals_has_no_separator(self):
        assert fmt_pt(214.0, 0) == "214"

    def test_two_decimals(self):
        assert fmt_pt(3.14159, 2) == "3,14"

    def test_defaults_to_one_decimal(self):
        assert fmt_pt(7.84) == "7,8"


class TestPtMessagesUseComma:
    def test_water_reason_uses_comma_decimal(self):
        from app.engine.pipeline import _build_reasons
        from app.engine.types import ConfidenceResult
        from app.engine.water_balance import WaterBalanceResult

        ctx = SimpleNamespace(defaults_used=[], missing_config=[])
        reasons = _build_reasons(
            ctx=ctx,
            wb=WaterBalanceResult(
                swc_current=0.18,
                depletion_mm=25.5,
                taw_mm=84.0,
                raw_mm=42.0,
                fc=0.28,
                pwp=0.14,
                root_depth_m=0.60,
            ),
            et0_val=4.6,
            etc_val=2.3,
            trigger_reason="O solo já perdeu água suficiente — chegou a hora de regar",
            fc_impact={"rain_next_48h_mm": 0.0},
            conf=ConfidenceResult(score=0.5, level="medium", penalties=[], warnings=[]),
            dose=None,
        )

        water_pt = [r.message_pt for r in reasons if r.category == "water_balance"][0]
        demand_pt = [r.message_pt for r in reasons if r.category == "evapotranspiration"][0]
        assert "25,5 mm" in water_pt
        assert "25.5" not in water_pt
        assert "2,3 mm" in demand_pt
        assert "4,6 mm" in demand_pt

    def test_trigger_reasons_use_comma_decimal(self):
        from app.engine.trigger import should_irrigate
        from app.engine.water_balance import WaterBalanceResult

        wb = WaterBalanceResult(
            swc_current=0.18,
            depletion_mm=25.5,
            taw_mm=84.0,
            raw_mm=42.0,
            fc=0.28,
            pwp=0.14,
            root_depth_m=0.60,
        )
        ctx = SimpleNamespace(
            irrigation_strategy="standard",
            rdi_factor=1.0,
            deficit_factor=1.0,
            rainfall_effectiveness=0.8,
        )
        decision, reason = should_irrigate(wb, ctx, forecast_rain_next_48h=0.0)
        assert decision is False
        assert "16,5 mm" in reason
        assert "16.5" not in reason
