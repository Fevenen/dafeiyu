import { build } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
await build({
  configFile: false,
  root: resolve("scripts"),
  base: "./",
  plugins: [react()],
  resolve: { alias: { "@": resolve("src/renderer/src") } },
  build: {
    outDir: resolve("../../tools/vision-ui-build"),
    emptyOutDir: false,
    rollupOptions: { input: resolve("scripts/vision-fixture.html") },
  },
});
