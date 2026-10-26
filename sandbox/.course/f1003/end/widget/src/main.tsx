import { createRoot } from "react-dom/client";
import App from "./App";
import Dashboard from "./Dashboard";
import "./App.css";

// the team's page is at #pilot, the customers' chat everywhere else
const page = location.hash === "#pilot" ? <Dashboard /> : <App />;
createRoot(document.getElementById("root")!).render(page);
