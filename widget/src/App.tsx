import { useState } from "react";
import Pilot from "./Pilot";

interface Message {
  from: "customer" | "assistant" | "error";
  text: string;
}

interface ChatReply {
  session_id: string;
  reply: string;
}

interface VerifyReply {
  session_id: string;
  verified: boolean;
}

type Step = "email" | "code" | "done";

export default function App() {
  if (location.pathname === "/pilot") return <Pilot />;
  return <Chat />;
}

function Chat() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [typing, setTyping] = useState(false);
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [verifyNote, setVerifyNote] = useState("");

  async function verify(path: "start" | "check") {
    const body = { session_id: sessionId, email, code };
    const response = await fetch(`/verify/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      setVerifyNote("Something went wrong. Please try again.");
      return;
    }
    const data: VerifyReply = await response.json();
    setSessionId(data.session_id);
    if (path === "start") {
      setStep("code");
      setVerifyNote("If this email has orders, we sent it a six-digit code.");
    } else if (data.verified) {
      setStep("done");
      setVerifyNote("");
    } else {
      setVerifyNote("That code did not work. Check it, or ask for a new one.");
    }
  }

  async function send(message: string) {
    setMessages((old) => [...old, { from: "customer", text: message }]);
    setText("");
    setTyping(true);
    const response = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, message }),
    });
    setTyping(false);
    if (!response.ok) {
      const note = "Something went wrong. Please ask for a person.";
      setMessages((old) => [...old, { from: "error", text: note }]);
      return;
    }
    const data: ChatReply = await response.json();
    setSessionId(data.session_id);
    setMessages((old) => [...old, { from: "assistant", text: data.reply }]);
  }

  return (
    <div className="chat">
      <header>
        DemoStore help
        <button onClick={() => send("I want to talk to a person.")}>
          Talk to a person
        </button>
      </header>
      {step !== "done" && (
        <form className="verify" onSubmit={(e) => {
          e.preventDefault();
          verify(step === "email" ? "start" : "check");
        }}>
          <span>To ask about an order, verify your email first.</span>
          {step === "email" ? (
            <input type="email" value={email} placeholder="Your email"
                   onChange={(e) => setEmail(e.target.value)} />
          ) : (
            <input value={code} placeholder="Six-digit code"
                   inputMode="numeric" maxLength={6}
                   onChange={(e) => setCode(e.target.value)} />
          )}
          <button type="submit">
            {step === "email" ? "Send code" : "Verify"}
          </button>
          {step === "code" && (
            <button type="button" onClick={() => setStep("email")}>
              New code
            </button>
          )}
          {verifyNote && <small>{verifyNote}</small>}
        </form>
      )}
      <div className="messages"><div>
        {messages.map((m, i) => (
          <p key={i} className={m.from}>{m.text}</p>
        ))}
        {typing && <p className="typing">The assistant is typing...</p>}
      </div></div>
      <form onSubmit={(e) => { e.preventDefault(); send(text); }}>
        <input value={text} onChange={(e) => setText(e.target.value)}
               placeholder="Type your question" />
      </form>
    </div>
  );
}
