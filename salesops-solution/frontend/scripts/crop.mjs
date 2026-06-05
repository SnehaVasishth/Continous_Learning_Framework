import sharp from "sharp";
import path from "node:path";
import fs from "node:fs";

const OUT = "C:/Users/Rituraj/Desktop/dark-mode-check-v2";

// Crop top 1100 of each dark screenshot for closer inspection
const files = fs.readdirSync(OUT).filter((f) => f.endsWith("-dark-before.png"));
for (const f of files) {
  const full = path.join(OUT, f);
  const m = await sharp(full).metadata();
  const top = Math.min(1100, m.height);
  const out = path.join(OUT, f.replace("-dark-before.png", "-dark-before-top.png"));
  await sharp(full).extract({ left: 0, top: 0, width: m.width, height: top }).toFile(out);
  console.log("WROTE", out);
}
