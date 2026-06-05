/**
 * mux.mjs — For each scene:
 *   1. probe the narration mp3 to get its duration
 *   2. time-stretch the scene's .webm to match (setpts), so audio + video line up
 *   3. transcode to mp4 + mux the narration as the audio track
 * Then concat all scene mp4s into out/demo.mp4 with crossfades.
 */
import { readFile, mkdir, writeFile, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { execFile as execFileCb } from "node:child_process";
import { promisify } from "node:util";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ffmpegInstaller from "@ffmpeg-installer/ffmpeg";
import ffprobeInstaller from "@ffprobe-installer/ffprobe";

const execFile = promisify(execFileCb);
const FFMPEG = ffmpegInstaller.path;
const FFPROBE = ffprobeInstaller.path;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TOUR_PATH = path.join(__dirname, "tour.json");
const OUT_DIR = path.join(__dirname, "out");
const CLIP_DIR = path.join(OUT_DIR, "clips");
const AUDIO_DIR = path.join(OUT_DIR, "audio");
const SCENE_MP4_DIR = path.join(OUT_DIR, "scenes_mp4");
const FINAL_PATH = path.join(OUT_DIR, "demo.mp4");

const tour = JSON.parse(await readFile(TOUR_PATH, "utf8"));
const { width, height, fps } = tour.video;

async function probeDurationSec(file) {
  const { stdout } = await execFile(FFPROBE, [
    "-v", "error",
    "-show_entries", "format=duration",
    "-of", "default=noprint_wrappers=1:nokey=1",
    file,
  ]);
  return parseFloat(stdout.trim());
}

async function ff(args, label) {
  try {
    await execFile(FFMPEG, args, { maxBuffer: 32 * 1024 * 1024 });
  } catch (err) {
    console.error(`ffmpeg failed: ${label}`);
    console.error(err.stderr?.toString?.() || err.message);
    throw err;
  }
}

await rm(SCENE_MP4_DIR, { recursive: true, force: true });
await mkdir(SCENE_MP4_DIR, { recursive: true });

const scenePaths = [];
for (const scene of tour.scenes) {
  const webm = path.join(CLIP_DIR, `${scene.id}.webm`);
  const audio = path.join(AUDIO_DIR, `${scene.id}.mp3`);
  if (!existsSync(webm)) { console.warn(`skip ${scene.id}: no video`); continue; }
  if (!existsSync(audio)) { console.warn(`skip ${scene.id}: no audio`); continue; }

  const audioDur = await probeDurationSec(audio);
  const rawVideoDur = await probeDurationSec(webm);
  // Per-scene `trimStartMs` cuts the leading navigation flash off the webm
  // before stretching. Use it when the loaded page should appear at frame 0
  // (e.g. when narration begins immediately and you don't want the prior
  // scene's tail or a blank loading frame to bleed in).
  const trimStartSec = (scene.trimStartMs || 0) / 1000;
  const videoDur = Math.max(0.1, rawVideoDur - trimStartSec);
  // Add a small tail so audio doesn't cut on word endings.
  const targetDur = audioDur + 0.4;
  const setptsFactor = (targetDur / videoDur).toFixed(6);

  const out = path.join(SCENE_MP4_DIR, `${scene.id}.mp4`);
  const trimLabel = trimStartSec > 0 ? ` (trim ${trimStartSec.toFixed(2)}s)` : "";
  console.log(`[${scene.id}] video=${videoDur.toFixed(2)}s${trimLabel} audio=${audioDur.toFixed(2)}s -> stretch x${setptsFactor}`);

  const inputArgs = trimStartSec > 0
    ? ["-ss", String(trimStartSec), "-i", webm]
    : ["-i", webm];

  await ff([
    "-y",
    ...inputArgs,
    "-i", audio,
    "-filter_complex",
      `[0:v]setpts=${setptsFactor}*PTS,fps=${fps},scale=${width}:${height}:flags=lanczos:force_original_aspect_ratio=decrease,pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[v]`,
    "-map", "[v]",
    "-map", "1:a:0",
    "-c:v", "libx264",
    "-preset", "slow",
    "-crf", "17",
    "-tune", "stillimage",
    "-pix_fmt", "yuv420p",
    "-color_primaries", "bt709",
    "-color_trc", "bt709",
    "-colorspace", "bt709",
    "-movflags", "+faststart",
    "-c:a", "aac",
    "-b:a", "192k",
    "-shortest",
    out,
  ], `mux ${scene.id}`);

  scenePaths.push(out);
}

if (scenePaths.length === 0) {
  console.error("No scene clips to concat. Run record.mjs + narrate.mjs first.");
  process.exit(1);
}

const concatList = scenePaths.map((p) => `file '${p.replace(/'/g, "'\\''")}'`).join("\n") + "\n";
const concatFile = path.join(SCENE_MP4_DIR, "concat.txt");
await writeFile(concatFile, concatList);

await ff([
  "-y",
  "-f", "concat",
  "-safe", "0",
  "-i", concatFile,
  "-c", "copy",
  "-movflags", "+faststart",
  FINAL_PATH,
], "final concat");

const finalDur = await probeDurationSec(FINAL_PATH);
console.log(`\nWrote ${path.relative(__dirname, FINAL_PATH)} (${finalDur.toFixed(1)}s)`);
