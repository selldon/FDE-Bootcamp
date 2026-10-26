import { useState } from "react";

interface Message {
  from: "customer" | "assistant" | "error";
  text: string;
}

interface ChatReply {
  session_id: string;
  reply: string;
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [text, setText] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [typing, setTyping] = useState(false);

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
