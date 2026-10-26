"""Policy pages cut into sections (B18, IT21, IT22): one section per `##` heading of a page's Markdown body.

A section keeps what the answer and the "valid today" rule need: page id, page version, heading, text, market,
valid dates and the page's link. Pure functions: the same pages give the same sections, in the same order.
"""
from datetime import date


class PolicyError(ValueError):
    """A page cannot be used; the message names it. Nothing is defaulted."""


def sections(page):
    """The sections of one page. A page with no market or no valid-from is an error naming the page."""
    label = f"page {page.get('id')} ({page.get('title')!r})"
    for field in ("market", "valid_from"):
        if not page.get(field):
            raise PolicyError(f"{label} has no {field.replace('_', '-')}")
    if not isinstance(page["valid_from"], date):
        raise PolicyError(f"{label} has a valid-from that is not a date")
    cuts, heading, lines = [], page.get("title") or "", []

    def close():
        text = "\n".join(lines).strip()
        if text:
            cuts.append({"page_id": page["id"], "version": page.get("version"), "heading": heading, "text": text,
                         "market": page["market"], "valid_from": page["valid_from"],
                         "valid_to": page.get("valid_to"), "link": page.get("link")})

    for line in (page.get("body") or "").splitlines():
        if line.startswith("## "):
            close()
            heading, lines = line[3:].strip(), []
        else:
            lines.append(line)
    close()
    return cuts


def all_sections(pages):
    """The sections of every page, in page order; one bad page raises."""
    return [s for page in pages for s in sections(page)]
