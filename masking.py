"""Card numbers are removed from a message before anything else sees it (B21)."""
import re

REMOVED = "[card number removed]"

# A run of digits, single spaces or dashes allowed between them. A run is judged whole, so a
# long number is never cut into a card-sized piece.
_RUN = re.compile(r"\d(?:[ -]?\d)*")


def luhn_valid(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _replace(match: re.Match) -> str:
    digits = re.sub(r"\D", "", match.group())
    if 13 <= len(digits) <= 19 and luhn_valid(digits):
        return REMOVED
    return match.group()


def mask_cards(text: str) -> str:
    """The text with every Luhn-valid 13-19 digit number replaced; the rest is kept as it was."""
    return _RUN.sub(_replace, text)
