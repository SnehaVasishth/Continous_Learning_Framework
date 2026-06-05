/**
 * run.mjs — Orchestrator: record -> narrate -> mux.
 *
 *   OPENAI_API_KEY=sk-... DEMO_BASE_URL=https://app.solution.example.com node run.mjs
 *
 * Flags:
 *   --skip-record   reuse existing out/clips/*.webm
 *   --skip-narrate  reuse existing out/audio/*.mp3
 */
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const args = new Set(process.argv.slice(2));

function step(name, file) {
  return new Promise((resolve, reject) => {
    console.log(`\n=== ${name} ===`);
    const p = spawn(process.execPath, [path.join(__dirname, file)], { stdio: "inherit" });
    p.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`${name} exited ${code}`))));
  });
}

if (!args.has("--skip-record")) await step("RECORD", "record.mjs");
if (!args.has("--skip-narrate")) await step("NARRATE", "narrate.mjs");
await step("MUX", "mux.mjs");
console.log("\nAll done. See out/demo.mp4");
