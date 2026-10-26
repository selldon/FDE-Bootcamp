import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// the pages call /chat and /pilot; Vite passes them on to our service
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/chat": "http://127.0.0.1:8000",
      "/pilot": "http://127.0.0.1:8000",
    },
    // reload the page after a short pause in the edits, not on every keystroke
    watch: { awaitWriteFinish: { stabilityThreshold: 1500 } },
  },
});
