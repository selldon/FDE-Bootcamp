"""docs/week-2-report.md, written from the page's numbers: nothing in it is typed by hand.

    python golive_report.py                    fetch GET /api/golive from the running service and write the report
    python golive_report.py --url http://localhost:8000 --out docs/week-2-report.md

`render(api)` takes the JSON the page itself gets. The recommendation follows the lines Lena signed: widen only when all four
lines hold for the two weeks; any line that does not hold, or fewer than 14 days, means the assistant stays where it is.
"""
import argparse
import json
import urllib.request
from pathlib import Path

import pilot

HERE = Path(__file__).parent
OUT = HERE / "docs" / "week-2-report.md"
KEYS = ("confidently_wrong", "hand_off", "unanswered", "rating")
WORDS = {1: "One", 2: "Two", 3: "Three", 4: "Four"}


def fetch(url):
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def pct(x):
    return "-" if x is None else f"{x * 100:.2f} %"


def pct_range(interval):
    return "-" if not interval else f"{interval[0] * 100:.1f} % to {interval[1] * 100:.1f} %"


def limit_text(key, limit):
    return {"confidently_wrong": f"at most {limit * 100:g} %", "hand_off": f"at least {limit * 100:g} %",
            "unanswered": f"at most {limit * 100:g} points worse", "rating": f"at most {limit:g} lower"}[key]


def observed_text(key, value):
    if value is None:
        return "-"
    if key in ("confidently_wrong", "hand_off"):
        return pct(value)
    if key == "unanswered":
        return f"{value * 100:+.1f} points"
    return f"{value:.2f} lower" if value >= 0 else f"{-value:.2f} higher"


def interval_text(key, interval):
    if not interval:
        return "-"
    if key in ("confidently_wrong", "hand_off"):
        return pct_range(interval)
    if key == "unanswered":
        return f"{interval[0] * 100:+.1f} to {interval[1] * 100:+.1f} points"
    return f"{interval[0]:+.2f} to {interval[1]:+.2f}"


def n_text(n):
    return " / ".join(f"{x:,}" for x in n) if isinstance(n, list) else f"{n:,}"


def breaches(api):
    """[(key, line)] of the window lines that do not hold, in the page's order."""
    window = api["lines"]["window"]
    return [(k, window[k]) for k in KEYS if window[k]["status"] == "does not hold"]


def headline(api):
    """(the verdict line, the recommendation line): the signed lines decide."""
    two, share = api["lines"]["two_weeks"], f"{api['settings']['share'] * 100:g} %"
    bad = breaches(api)
    if bad:
        names = "; ".join(f"{line['name']}, {line['detail']} ({pct(line['value'])}), limit {limit_text(k, line['limit'])}"
                          if k == "confidently_wrong" else line["name"] for k, line in bad)
        count = WORDS.get(len(bad), str(len(bad)))
        verb = "line does not hold" if len(bad) == 1 else "lines do not hold"
        early = f" (only {two['days']} of {two['needed']} days so far)" if two["days"] < two["needed"] else ""
        verdict = f"**{count} {verb} over the two weeks: {names}.{early}**"
    elif two["status"] != "holds":
        verdict = (f"**Not enough yet: {two['days']} of {two['needed']} days with chats, or a line without data; "
                   f"no verdict on the two weeks.**")
    else:
        verdict = f"**All four lines hold over the two weeks ({two['days']} of {two['needed']} days).**"
    if bad or two["status"] != "holds":
        word = "do not widen" if bad else "do not widen yet"
        advice = f"**Recommendation: {word}. The assistant stays at {share}, and returns stay off.**"
    else:
        advice = ("**Recommendation: widen to 25 % and add `return_request` to the live intents (drafts only: no refund is "
                  "ever paid by the assistant).**")
    return verdict, advice


def scale(api):
    """The arithmetic of the scale-up, from the page's window numbers."""
    group = api["window"]["assistant"]
    weeks = api["days_with_chats"] / 7
    share = api["settings"]["share"]
    resolved_week = group["resolved"] / weeks
    hours_now = resolved_week * pilot.PERSON_MINUTES / 60
    chats_100 = group["decided"] / weeks / share
    return {"weeks": weeks, "share": share, "resolved_week": resolved_week, "hours_now": hours_now,
            "hours_100": hours_now / share, "hours_25": hours_now / share * 0.25, "chats_100": chats_100,
            "resolved_100": resolved_week / share}


def render(api):
    verdict, advice = headline(api)
    share, window = api["settings"]["share"], api["lines"]["window"]
    s = scale(api)
    wrong = window["confidently_wrong"]
    visitors_per_day = json.loads((HERE / "sim_assumptions.json").read_text())["visitors_per_day"]
    out = [f"# Week 2 report - the go-live at {share * 100:g} %", "",
           (f"**Simulated.** Every chat behind these numbers is simulated traffic: {api['simulated']:,} of {api['total']:,} "
           f"rows are labelled simulated, and no real customer took part."), "", verdict, "", advice, "",
           f"## The four lines over the two weeks (days 1-{api['days_with_chats']})", "",
           "| Line | Limit | Observed | n | 95 % interval | Status |", "|---|---|---|---|---|---|"]
    for key in KEYS:
        line = window[key]
        out.append(f"| {line['name']} | {limit_text(key, line['limit'])} | {observed_text(key, line['value'])} | "
                   f"{n_text(line['n'])} | {interval_text(key, line['interval'])} | {line['status']} |")
    alerts = ", ".join(str(d) for d in api["lines"]["alert_days"]) or "none"
    out += ["", f"Days with a confidently-wrong alert: {alerts}. The two-week reading: **{api['lines']['two_weeks']['status']}**."]
    if api["drill_days"]:
        out += ["", "## The drill (days after 14)", "",
                (f"Days {', '.join(str(d) for d in api['drill_days'])} are drill days: a night with no carrier file, run on purpose. "
                f"They are not in the lines above; the week and the two weeks read days 1-{api['days_with_chats']}."), ""]
        for d in api["drill_days"]:
            group = api["by_day"][str(d)]["assistant"]
            out.append(f"- day {d}: {group['confidently_wrong']} of {group['chats']} assistant chats confidently wrong")
        out += ["", "The details are in `docs/drill-notes.md`."]
    out += ["", "## Operator hours saved a week", "",
            (f"Resolved assistant chats a week x {pilot.PERSON_MINUTES} minutes for one contact with a person "
            f"(`pilot.PERSON_MINUTES`), scaled from the {share * 100:g} % sample: {api['window']['assistant']['resolved']} resolved "
            f"chats in {s['weeks']:g} weeks = {s['resolved_week']:.1f} a week."), "",
            "| Share of visitors | Resolved assistant chats a week | Hours saved a week |", "|---|---|---|",
            f"| {share * 100:g} % (now) | {s['resolved_week']:.1f} | {s['hours_now']:.1f} hours |",
            f"| 25 % (the step not taken) | {s['resolved_100'] * 0.25:.1f} | {s['hours_25']:.1f} hours |",
            f"| 100 % | {s['resolved_100']:.1f} | {s['hours_100']:.1f} hours |",
            "", "## What 100 % would mean", "",
            (f"- About {s['chats_100']:,.0f} assistant chats a week (the {api['window']['assistant']['decided']} of the window, per "
            f"week, divided by the share)."),
            f"- {s['hours_100']:.1f} hours of operator time saved a week.",
            (f"- Confidently wrong answers a week: about {s['chats_100'] * (wrong['value'] or 0):.0f} at the observed rate "
            f"({pct(wrong['value'])}), and up to {s['chats_100'] * (wrong['interval'] or [0, 0])[1]:.0f} at the upper end of "
            f"its interval ({pct_range(wrong['interval'])})."),
            (f"- A sample of {wrong['n']} chats cannot show the rate is below {wrong['limit'] * 100:g} %: the upper end of its "
            f"interval is {pct((wrong['interval'] or [0, 0])[1])}."),
            "", "## Assumptions, out loud", "",
            (f"- **Simulated traffic.** Visitors, questions and follow-ups are seeded scripts ({visitors_per_day} visitors a day in "
            f"`sim_assumptions.json`); the real volume and mix are not known. Every row is labelled simulated."),
            ("- **Seeded outcomes.** Control outcomes and every rating are drawn from rules in `sim_assumptions.json`, not measured "
            "from customers. Only the assistant's answers, hand-offs and cost are real model behaviour, so the rating line holds by "
            "construction."),
            f"- **Repeat contact is not measured.** {api['repeat_note']}",
            (f"- **Linear scale-up.** Hours and wrong answers at another share multiply the sample by 1 / share: the same mix, the same "
            f"resolve rate. {pilot.PERSON_MINUTES} minutes for a contact with a person is a flat assumption."),
            (f"- **Tiny samples.** {api['window']['assistant']['decided']} assistant chats, {window['hand_off']['n']} of them needing a "
            f"person. Read the 95 % intervals, not only the observed values: a line that holds on its observed value is not proven "
            f"below its limit unless its interval is."),
            (f"- **Only order status is live.** {api['window']['person']} assistant-group chats on other questions went straight to a "
            f"person and are not compared."),
            ("- **The scoring rules.** Each answer is scored against the carrier's file the service had loaded. A reply that says the "
            "news is old is not a status given as fact; a negated status is not a claim; a partly shipped order whose parcels are all "
            "delivered is right only if the reply names the part-shipped status. The decisions are in `docs/plan-golive.md`."),
            ("- **The night file hour.** 03:00 UTC for the carrier's night file is a working value until Ravi Menon's team confirms it "
            "(OQ-5 in `docs/requirements.md`)."),
            "", "## Where these numbers come from", "",
            (f"Generated by `python golive_report.py` from `GET /api/golive` (as of {api['as_of']}). Nothing here is typed by hand; "
            f"run it again to refresh."), ""]
    return "\n".join(out)


def main(argv=None, fetch=fetch):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    text = render(fetch(args.url.rstrip("/") + "/api/golive"))
    Path(args.out).write_text(text)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
