/**
 * narrate.mjs — Generates one .mp3 per scene using OpenAI TTS.
 *
 *   OPENAI_API_KEY=sk-... node narrate.mjs
 */
import OpenAI from "openai";
import { existsSync } from "node:fs";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TOUR_PATH = path.join(__dirname, "tour.json");
const AUDIO_DIR = path.join(__dirname, "out", "audio");

if (!process.env.OPENAI_API_KEY) {
  console.error("ERROR: OPENAI_API_KEY is not set.");
  process.exit(1);
}

const tour = JSON.parse(await readFile(TOUR_PATH, "utf8"));
const { model, voice, format, speed } = {
  model: "tts-1-hd",
  voice: "alloy",
  format: "mp3",
  speed: 1.0,
  ...(tour.narration ?? {}),
};

await mkdir(AUDIO_DIR, { recursive: true });

const client = new OpenAI();

let generated = 0;
let cached = 0;
for (const scene of tour.scenes) {
  const outPath = path.join(AUDIO_DIR, `${scene.id}.${format}`);
  if (existsSync(outPath)) {
    console.log(`[${scene.id}] cached (${path.relative(__dirname, outPath)})`);
    cached += 1;
    continue;
  }
  console.log(`[${scene.id}] TTS (${voice}, ${model}) -> ${path.relative(__dirname, outPath)}`);
  const res = await client.audio.speech.create({
    model,
    voice,
    input: scene.narration,
    response_format: format,
    speed,
  });
  const buf = Buffer.from(await res.arrayBuffer());
  await writeFile(outPath, buf);
  generated += 1;
}

console.log(`\nDone. Generated ${generated} narration clips (${cached} cached).`);
