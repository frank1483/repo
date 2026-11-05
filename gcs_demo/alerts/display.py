"""Rule display only: preserve signed numeric estimates for all calculations."""
import math


def landing_pct_text(value, digits=1):
    """A negative landing estimate is a shortage, never a clamped estimate.

    This function does not change the source number or produce model evidence.
    """
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise ValueError("finite landing percentage required")
    if not isinstance(digits, int) or isinstance(digits, bool) or not 0 <= digits <= 6:
        raise ValueError("display precision must be an integer from 0 to 6")
    if value < 0:
        # Preserve a small negative shortage that would otherwise round to zero.
        shown = f"{abs(value):.{digits}f}"
        if float(shown) == 0:
            shown = f"小於 {10 ** -digits:.{digits}f}"
        return f"低於 0%（短缺 {shown}%）"
    return f"{value:.{digits}f}%"
