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
const PRODUCT = 0.99; // a ready product, per chat it counts as resolved

export default function Dashboard() {
  const [pilot, setPilot] = useState<Pilot | null>(null);

  useEffect(() => {
    fetch("/pilot").then((r) => r.json()).then(setPilot);
  }, []);

  if (!pilot) return <p className="dashboard">Loading...</p>;
  // a product that counts every chat without a person bills those who left too
  const billed = pilot.resolved + pilot.left;
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
      <h3>Cost of one truly resolved chat</h3>
      <table><tbody>
        <tr><td>Our pilot, model calls</td><td>${pilot.per_resolved}</td></tr>
        <tr><td>A person, one contact</td><td>${PERSON}</td></tr>
        <tr><td>A ready product, billed for {billed} chats</td>
          <td>${(PRODUCT * billed / pilot.resolved).toFixed(2)}</td></tr>
      </tbody></table>
      <h3>Time back for the team: {pilot.minutes_back} minutes</h3>
    </div>
  );
}
