"""The farm-summary prompt must not tell the model to claim a decision the engine
never made (A4 live evaluation, 2026-09-23).

It said: if no sector irrigates, write "Sem necessidade: todos os sectores" — without
excluding sectors that have no recommendation. The model followed it faithfully and
told growers an unassessed sector needed no water in 10 of 10 runs. The live
evaluation measures the behaviour; this pins the contract against a silent revert.
"""

import pytest

from app.ai.prompt_templates import get_farm_summary_template


@pytest.mark.parametrize(
    ("language", "conditional"),
    [
        ("pt", '"Sem necessidade: todos os sectores" se todos tiverem "skip" ou "defer"'),
        ("en", '"No action: all sectors" if every sector is "skip" or "defer"'),
    ],
)
def test_all_sectors_are_resting_only_when_every_sector_is_skip_or_defer(language, conditional):
    # The unconditional form ("if none irrigates, write 'all sectors'") is what the
    # model followed into claiming an unassessed sector needed no water.
    assert conditional in get_farm_summary_template(language)


@pytest.mark.parametrize(
    ("language", "topic"), [("pt", "Sem recomendação"), ("en", "No recommendation")]
)
def test_a_sector_without_a_decision_gets_its_own_topic(language, topic):
    assert topic in get_farm_summary_template(language)
