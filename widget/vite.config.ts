import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// the widget calls /chat, /verify and /api (the pilot page); while we develop, Vite passes it on to our service
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/chat": "http://127.0.0.1:8000",
      "/verify": "http://127.0.0.1:8000",
      "/api": "http://127.0.0.1:8000",
    },
    // reload the page after a short pause in the edits, not on every keystroke
    watch: { awaitWriteFinish: { stabilityThreshold: 1500 } },
  },
});
