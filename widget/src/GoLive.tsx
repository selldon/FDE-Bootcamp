import { useEffect, useState } from "react";

type Interval = [number, number, number] | null;

interface Group {
  chats: number;
  decided: number;
  resolved: number;
  handed_off: number;
  unanswered: number;
  repeat_contacts: number;
  repeat_known: number;
  rating: number | null;
  rating_n: number;
  cost_per_contact: number | null;
  confidently_wrong: number;
}

interface Window {
  total: number;
  person: number;
  assistant: Group;
  control: Group;
  difference: {
    n_assistant: number;
    n_control: number;
    resolved: Interval;
    handed_off: Interval;
    unanswered: Interval;
    repeat: Interval;
    rating: Interval;
    cost_per_contact: number | null;
  };
}

interface Line {
  name: string;
  limit: number;
  value: number | null;
  n: number | [number, number];
  status: string;
  interval: [number, number] | null;
  detail: string;
}

interface Settings {
  share: number;
  intents: string[];
  on: boolean;
  changed_at: string | null;
}

interface Data {
  repeat_note?: string;
  drill_days?: number[];
  total: number;
  simulated: number;
  last_day: number | null;
  days_with_chats: number;
  day: Window;
  week: Window;
  window: Window;
  settings: Settings;
  lines: {
    day: { confidently_wrong: Line; alert: boolean };
    week: Record<string, Line>;
    window: Record<string, Line>;
    alert_days: number[];
    two_weeks: { status: string; days: number; needed: number };
  };
}

const NO_DATA = "not enough yet";

function pct(x: number | null, digits = 1) {
  return x === null ? "-" : `${(100 * x).toFixed(digits)}%`;
}

// A difference of two proportions, in percentage points, with its 95 % interval.
function points(d: Interval) {
  if (!d) return NO_DATA;
  const f = (x: number) => (100 * x).toFixed(1);
  return `${f(d[0])} pts (95%: ${f(d[1])} to ${f(d[2])})`;
}

function rate(part: number, whole: number) {
  return whole ? `${pct(part / whole)} (${part} of ${whole})` : "-";
}

function money(x: number | null): string {
  if (x === null) return "-";
  if (x < 0) return `-${money(-x)}`;
  return x >= 0.1 ? `$${x.toFixed(2)}` : `$${x.toFixed(4)}`;
}

function ratingText(d: Interval) {
  if (!d) return NO_DATA;
  return `${d[0].toFixed(2)} (95%: ${d[1].toFixed(2)} to ${d[2].toFixed(2)})`;
}

function lineValue(l: Line) {
  if (l.value === null) return NO_DATA;
  const rating = l.name.startsWith("rating");
  const v = rating ? `${l.value.toFixed(2)} pts` : `${(100 * l.value).toFixed(1)}${l.name.startsWith("left") ? " pts" : "%"}`;
  const limit = rating ? `${l.limit} pts` : `${(100 * l.limit).toFixed(0)}${l.name.startsWith("left") ? " pts" : "%"}`;
  const iv = l.interval
    ? ` (95%: ${rating ? l.interval.map((x) => x.toFixed(2)).join(" to ") : l.interval.map((x) => (100 * x).toFixed(1)).join(" to ")})`
    : "";
  return `${v}${iv}, limit ${limit}`;
}

function Lines({ title, lines }: { title: string; lines: Line[] }) {
  return (
    <>
      <h3>{title}</h3>
      <table>
        <thead><tr><th>Line</th><th>Now</th><th>n</th><th>Status</th></tr></thead>
        <tbody>
          {lines.map((l) => (
            <tr key={l.name} className={l.status === "does not hold" ? "breach" : ""}>
              <td>{l.name}</td>
              <td>{lineValue(l)}</td>
              <td>{Array.isArray(l.n) ? `${l.n[0]} / ${l.n[1]}` : l.n}</td>
              <td>{l.status === "holds" ? "holds" : l.status === "does not hold" ? "does not hold" : NO_DATA}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Compare({ title, w, repeatNote }: { title: string; w: Window; repeatNote?: string }) {
  const a = w.assistant;
  const c = w.control;
  const d = w.difference;
  return (
    <>
      <h3>{title}</h3>
      <table>
        <thead>
          <tr><th></th><th>Assistant (n = {a.decided})</th><th>Control (n = {c.decided})</th><th>Difference (assistant - control)</th></tr>
        </thead>
        <tbody>
          <tr><th>Resolved</th><td>{rate(a.resolved, a.decided)}</td><td>{rate(c.resolved, c.decided)}</td><td>{points(d.resolved)}</td></tr>
          <tr><th>Handed off</th><td>{rate(a.handed_off, a.decided)}</td><td>{rate(c.handed_off, c.decided)}</td><td>{points(d.handed_off)}</td></tr>
          <tr><th>Left without an answer</th><td>{rate(a.unanswered, a.decided)}</td><td>{rate(c.unanswered, c.decided)}</td><td>{points(d.unanswered)}</td></tr>
          <tr><th>Repeat contact in 7 days</th><td>not measured</td><td>not measured</td><td>{repeatNote ?? "not measured"}</td></tr>
          <tr>
            <th>Rating (1-5)</th>
            <td>{a.rating === null ? "-" : a.rating.toFixed(2)} (n = {a.rating_n})</td>
            <td>{c.rating === null ? "-" : c.rating.toFixed(2)} (n = {c.rating_n})</td>
            <td>{ratingText(d.rating)}</td>
          </tr>
          <tr>
            <th>Cost per contact</th><td>{money(a.cost_per_contact)}</td><td>{money(c.cost_per_contact)}</td>
            <td>{d.cost_per_contact === null ? NO_DATA : money(d.cost_per_contact)}</td>
          </tr>
        </tbody>
      </table>
      {w.person > 0 && <p>{w.person} chats went straight to a person (switch off, or the question is not live yet); they are not compared.</p>}
    </>
  );
}

export default function GoLive() {
  const [data, setData] = useState<Data | null>(null);
  const [note, setNote] = useState("");

  async function load() {
    try {
      const response = await fetch("/api/golive");
      if (!response.ok) {
        setNote("Could not load the go-live data.");
        return;
      }
      setData(await response.json());
    } catch {
      setNote("Could not load the go-live data: the answer was not JSON, or the service did not respond.");
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function flip(on: boolean) {
    const started = performance.now();
    const response = await fetch("/api/golive/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ on }),
    });
    if (!response.ok) {
      setNote("The switch was not changed.");
      return;
    }
    const seconds = ((performance.now() - started) / 1000).toFixed(1);
    setNote(`The assistant is now ${on ? "on" : "off"} (the service answered in ${seconds} s).`);
    await load();
  }

  if (!data) return <main className="pilot"><p>{note || "Loading..."}</p></main>;

  const s = data.settings;
  const l = data.lines;
  const two = l.two_weeks;
  return (
    <main className="pilot">
      <h1>Go-live: assistant against control</h1>
      <p className="estimate banner-sim" role="note">
        <strong>Simulated traffic.</strong> Visitors, outcomes and ratings come from a seeded simulation, not from real customers
        ({data.simulated} of {data.total} chats are simulated).
      </p>

      {l.day.alert && (
        <p className="alert" role="alert">
          ALERT: the assistant gave a confidently wrong answer on the latest day ({l.day.confidently_wrong.detail}). Switch it off.
        </p>
      )}
      {l.alert_days.length > 0 && !l.day.alert && (
        <p className="estimate">Days with an alert so far: {l.alert_days.length}.</p>
      )}

      <h2>Switch</h2>
      <table>
        <tbody>
          <tr><th>Assistant</th><td><strong>{s.on ? "ON" : "OFF"}</strong></td></tr>
          <tr><th>Share of visitors</th><td>{pct(s.share, 0)}</td></tr>
          <tr><th>Live questions</th><td>{s.intents.join(", ") || "-"}</td></tr>
        </tbody>
      </table>
      <p>
        <button disabled={!s.on} onClick={() => flip(false)}>Switch the assistant off</button>
        <button disabled={s.on} onClick={() => flip(true)}>Switch the assistant on</button>
        {" "}New chats read the switch at once; a chat already open goes to a person on its next message.
      </p>
      {note && <p role="status" className="note">{note}</p>}

      <h2>Do the lines hold?</h2>
      <p className={two.status === "holds" ? "" : "estimate"}>
        Two weeks: <strong>{two.status === "holds" ? "holds" : two.status === "does not hold" ? "does not hold" : NO_DATA}</strong>
        {" "}({two.days} of {two.needed} days with chats).
      </p>
      {(data.drill_days ?? []).length > 0 && (
        <p className="estimate">
          Day{(data.drill_days ?? []).length > 1 ? "s" : ""} {(data.drill_days ?? []).join(", ")} {(data.drill_days ?? []).length > 1 ? "are" : "is a"}
          {" "}drill {(data.drill_days ?? []).length > 1 ? "days" : "day"} (a night with no carrier file). {(data.drill_days ?? []).length > 1 ? "They are" : "It is"}
          {" "}read by the latest-day alert and left out of the week and the two weeks.
        </p>
      )}
      <Lines title="Latest day (the alert)" lines={[l.day.confidently_wrong]} />
      <Lines title="Week so far" lines={Object.values(l.week)} />
      <Lines title="Whole window" lines={Object.values(l.window)} />

      <h2>The two groups</h2>
      <Compare title="Latest day" w={data.day} repeatNote={data.repeat_note} />
      <Compare title="Week so far" w={data.week} repeatNote={data.repeat_note} />
      <Compare title="Whole window" w={data.window} repeatNote={data.repeat_note} />
    </main>
  );
}
