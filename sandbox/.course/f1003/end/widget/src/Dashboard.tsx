import { useEffect, useState } from "react";
import "./Dashboard.css";

interface Pilot {
  chats: number;
  resolved: number;
  handed: number;
  left: number;
  reasons: Record<string, number>;
  per_chat: number;
  per_resolved: number;
  minutes_back: number;
}

const PERSON = 7; // dollars for one contact with a person (the baseline)

export default function Dashboard() {
  const [pilot, setPilot] = useState<Pilot | null>(null);

  useEffect(() => {
    fetch("/pilot").then((r) => r.json()).then(setPilot);
  }, []);

  if (!pilot) return <p className="dashboard">Loading...</p>;
  const rows: [string, number][] = [
    ["Resolved", pilot.resolved],
    ["Handed to a person", pilot.handed],
    ["Left without an answer", pilot.left],
  ];
  return (
    <div className="dashboard">
      <h2>Pilot in shadow mode: {pilot.chats} chats</h2>
      <table><tbody>
        {rows.map(([name, count]) => (
          <tr key={name}>
            <td>{name}</td>
            <td>{count}</td>
            <td>{Math.round((100 * count) / pilot.chats)}%</td>
          </tr>
        ))}
      </tbody></table>
      <h3>Why chats went to a person</h3>
      <table><tbody>
        {Object.entries(pilot.reasons).map(([reason, count]) => (
          <tr key={reason}><td>{reason}</td><td>{count}</td></tr>
        ))}
      </tbody></table>
      <h3>Cost</h3>
      <table><tbody>
        <tr><td>One chat with the assistant</td><td>${pilot.per_chat}</td></tr>
        <tr><td>One contact with a person</td><td>${PERSON}</td></tr>
        <tr><td>Cheaper</td>
          <td>{Math.round(PERSON / pilot.per_chat)} times</td></tr>
      </tbody></table>
    </div>
  );
}
