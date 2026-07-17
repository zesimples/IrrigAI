"""pt-PT number formatting for user-facing strings.

The UI language is European Portuguese, so decimals in PT-facing text use the
comma separator ("7,8 mm"). English (`message_en`) strings keep the dot.
"""


def fmt_pt(value: float, digits: int = 1) -> str:
    """Format a number with the Portuguese comma decimal separator."""
    return f"{value:.{digits}f}".replace(".", ",")
