import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Dev server on 127.0.0.1:5173 (an origin the API allows through CORS).
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
