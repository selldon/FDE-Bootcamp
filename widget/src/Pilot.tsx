import { useEffect, useState } from "react";

interface Row {
  key: string | null;
  chats: number;
  resolved: number;
}

interface Pilot {
  total: number;
  resolved: number;
  days: Row[];
  markets: Row[];
  actions: Row[];
  intents: Row[];
  unclassified: number;
  criterion: { chats: number; resolved: number; rate: number | null; target: number };
  checked: {
    sample: number;
    verdicts: Record<Verdict, number>;
    confidently_wrong: number;
  };
  cost: {
    priced: number;
    unpriced: number;
    total: number;
    per_chat: number | null;
    priced_resolved: number;
    per_resolved_chat: number | null;
  };
  baseline: { person_cost: number; person_minutes: number; product_cost: number };
  sentences: string[];
}

interface Chat {
  number: string;
  opened_at: string;
  market: string | null;
  intent: string | null;
  action: string | null;
  message: string | null;
  answer: string | null;
  agent_reply: string | null;
}

type Verdict = "same" | "better" | "worse" | "wrong";

const VERDICTS: { id: Verdict; label: string }[] = [
  { id: "same", label: "Same" },
  { id: "better", label: "Assistant better" },
  { id: "worse", label: "Assistant worse" },
  { id: "wrong", label: "Wrong" },
];

const NAME_KEY = "pilot-marker-name";

function pct(part: number, whole: number) {
  return whole ? `${Math.round((100 * part) / whole)}%` : "-";
}

function money(x: number | null) {
  if (x === null) return "-";
  return x >= 0.1 ? `$${x.toFixed(2)}` : `$${x.toFixed(4)}`;
}

function label(key: string | null, none: string) {
  return key === null ? none : key;
}

// Every rate sits next to its base: "resolved / chats".
function Breakdown({ title, rows, none }: { title: string; rows: Row[]; none: string }) {
  return (
    <table>
      <caption>{title}</caption>
      <thead>
        <tr><th>{title}</th><th>Chats</th><th>Would have resolved</th><th>Rate (of chats)</th></tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key ?? "(none)"}>
            <td>{label(r.key, none)}</td>
            <td>{r.chats}</td>
            <td>{r.resolved}</td>
            <td>{pct(r.resolved, r.chats)} ({r.resolved} of {r.chats})</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Pilot() {
  const [data, setData] = useState<Pilot | null>(null);
  const [sample, setSample] = useState<Chat[]>([]);
  const [name, setName] = useState(() => localStorage.getItem(NAME_KEY) ?? "");
  const [sure, setSure] = useState<Record<string, boolean>>({});
  const [note, setNote] = useState("");

  async function load() {
    const [numbers, list] = await Promise.all([fetch("/api/pilot"), fetch("/api/pilot/sample")]);
    if (!numbers.ok || !list.ok) {
      setNote("Could not load the pilot data.");
      return;
    }
    setData(await numbers.json());
    setSample(await list.json());
  }

  useEffect(() => {
    load();
  }, []);

  function changeName(value: string) {
    setName(value);
    localStorage.setItem(NAME_KEY, value);
  }

  async function mark(number: string, verdict: Verdict) {
    if (!name.trim()) {
      setNote("Type your name first: it is stored with each mark.");
      return;
    }
    const response = await fetch("/api/pilot/mark", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        number,
        marker: name,
        verdict,
        sounded_sure: verdict === "wrong" && !!sure[number],
      }),
    });
    if (!response.ok) {
      setNote("The mark was not stored.");
      return;
    }
    setNote(`Stored: ${number} marked "${verdict}" by ${name.trim()}.`);
    await load();
  }

  if (!data) return <main className="pilot"><p>{note || "Loading..."}</p></main>;

  const c = data.criterion;
  const k = data.cost;
  const ch = data.checked;
  return (
    <main className="pilot">
      <h1>Pilot: shadow mode</h1>
      <p className="estimate">
        <strong>"Would have resolved" is an estimate:</strong> no customer saw these answers, so nobody could react to them.
      </p>

      {data.sentences.map((s, i) => <p key={i} className="sentence">{s}</p>)}

      <h2>Totals</h2>
      <table>
        <tbody>
          <tr><th>Shadow chats</th><td>{data.total}</td></tr>
          <tr><th>Would have resolved</th><td>{data.resolved} of {data.total} ({pct(data.resolved, data.total)})</td></tr>
          <tr>
            <th>"Where is my order" chats resolved (aim {Math.round(c.target * 100)}%)</th>
            <td>{c.resolved} of {c.chats} ({pct(c.resolved, c.chats)})</td>
          </tr>
          <tr><th>Without an intent (old rows)</th><td>{data.unclassified} of {data.total}</td></tr>
        </tbody>
      </table>

      <Breakdown title="Day" rows={data.days} none="(no date)" />
      <Breakdown title="Market" rows={data.markets} none="(no market)" />
      <Breakdown title="Action" rows={data.actions} none="(no action)" />
      <Breakdown title="Intent" rows={data.intents} none="unclassified" />

      <h2>Checked sample</h2>
      <table>
        <thead><tr><th>Verdict</th><th>Chats</th><th>Share (of {ch.sample} checked)</th></tr></thead>
        <tbody>
          {VERDICTS.map((v) => (
            <tr key={v.id}>
              <td>{v.label}</td>
              <td>{ch.verdicts[v.id]}</td>
              <td>{pct(ch.verdicts[v.id], ch.sample)} ({ch.verdicts[v.id]} of {ch.sample})</td>
            </tr>
          ))}
          <tr>
            <td>Wrong and sounded sure</td>
            <td>{ch.confidently_wrong}</td>
            <td>{pct(ch.confidently_wrong, ch.sample)} ({ch.confidently_wrong} of {ch.sample})</td>
          </tr>
        </tbody>
      </table>

      <h2>Cost</h2>
      <table>
        <tbody>
          <tr><th>Model calls, priced chats</th><td>{money(k.total)} over {k.priced} of {data.total} chats</td></tr>
          <tr><th>Per chat</th><td>{money(k.per_chat)} (of {k.priced} priced)</td></tr>
          <tr>
            <th>Per resolved chat</th>
            <td>{money(k.per_resolved_chat)} (of {k.priced_resolved} priced and resolved)</td>
          </tr>
          <tr><th>Unpriced (no stored tokens)</th><td>{k.unpriced} of {data.total}</td></tr>
          <tr>
            <th>Baseline</th>
            <td>
              person {money(data.baseline.person_cost)} and {data.baseline.person_minutes} min per contact;
              ready-made product {money(data.baseline.product_cost)} per resolution
            </td>
          </tr>
        </tbody>
      </table>

      <h2>Mark chats</h2>
      <p>
        <label>
          Your name:{" "}
          <input value={name} onChange={(e) => changeName(e.target.value)} placeholder="Name" />
        </label>
      </p>
      {note && <p role="status" className="note">{note}</p>}
      {sample.length === 0 && <p>No unmarked chats with an agent reply today.</p>}
      {sample.map((chat) => (
        <section key={chat.number} className="pair">
          <h3>
            {chat.number} - {chat.market ?? "(no market)"} - {chat.intent ?? "unclassified"} - assistant: {chat.action ?? "-"}
          </h3>
          <table>
            <thead><tr><th>Customer</th><th>Assistant (shadow)</th><th>Agent (real)</th></tr></thead>
            <tbody>
              <tr><td>{chat.message}</td><td>{chat.answer}</td><td>{chat.agent_reply}</td></tr>
            </tbody>
          </table>
          <p>
            {VERDICTS.map((v) => (
              <button key={v.id} onClick={() => mark(chat.number, v.id)}>{v.label}</button>
            ))}
            {" "}
            <label>
              <input
                type="checkbox"
                checked={!!sure[chat.number]}
                onChange={(e) => setSure({ ...sure, [chat.number]: e.target.checked })}
              />{" "}
              Sounded sure (only counts with "Wrong")
            </label>
          </p>
        </section>
      ))}
    </main>
  );
}
