# SalesOps Demo Recorder

Records a narrated ~60s walkthrough of the SalesOps main app + governance app
and produces `out/demo.mp4` ready to share with the client.

## How it works

```
tour.json   ── scene list: { path, narration, settleMs, actions }
   │
   ├─► record.mjs   Playwright → out/clips/<id>.webm   (one clip per scene)
   ├─► narrate.mjs  OpenAI TTS → out/audio/<id>.mp3
   └─► mux.mjs      ffmpeg: time-stretch each clip to its narration,
                    mux audio, concat → out/demo.mp4
```

## One-time setup

```bash
cd scripts/demo-recorder
npm install
npx playwright install chromium
```

## Run

```bash
OPENAI_API_KEY=sk-... \
DEMO_BASE_URL=https://app.solution.example.com \
npm run all
```

Re-runs:
- `node run.mjs --skip-record` — re-narrate + re-mux only (e.g. you edited narration).
- `node run.mjs --skip-narrate` — re-record + re-mux only (e.g. UI changed).

## Editing the tour

Open `tour.json`. Each scene has:

- `path` — appended to `DEMO_BASE_URL`. Governance pages use `/keysight-salesops-governance/...`.
- `narration` — the line read aloud. Keep it 1 sentence, ~7-9 seconds when spoken.
- `settleMs` — pause after navigation before the recording is cut.
- `actions[]` — optional UI interactions: `hoverFirst`, `click`, `scroll`, `wait`.

## Notes

- `width: 1440, height: 900, fps: 30` matches a standard demo aspect.
- Audio is the source of truth — each scene's video is time-stretched to match
  its narration length, so timing is automatic.
- ffmpeg + ffprobe ship via `@ffmpeg-installer/ffmpeg` and
  `@ffprobe-installer/ffprobe`. No system install required.
