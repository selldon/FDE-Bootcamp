"""Card numbers are removed from a message before anything else sees it (B21)."""
import re

REMOVED = "[card number removed]"

# A run of digit groups, joined by 1-3 spaces, no-break spaces, dashes, dots or slashes. A group of digits is never cut.
_RUN = re.compile(r"\d+(?:[ \u00a0.\-/]{1,3}\d+)*")
_GROUP = re.compile(r"\d+")


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
    """Within one run, remove every stretch of whole digit groups that is a card number (13-19 digits, Luhn).

    Looking at stretches, not only the whole run, catches a card typed next to a CVV or a second card.
    """
    run = match.group()
    groups = list(_GROUP.finditer(run))
    out, taken, i = [], 0, 0
    while i < len(groups):
        for j in range(len(groups) - 1, i - 1, -1):
            digits = "".join(g.group() for g in groups[i:j + 1])
            if 13 <= len(digits) <= 19 and luhn_valid(digits):
                out.append(run[taken:groups[i].start()] + REMOVED)
                taken, i = groups[j].end(), j
                break
        i += 1
    return "".join(out) + run[taken:]


def mask_cards(text: str) -> str:
    """The text with every Luhn-valid 13-19 digit number replaced; the rest is kept as it was."""
    return _RUN.sub(_replace, text)
