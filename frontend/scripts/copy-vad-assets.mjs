// Copies the voice activity detector files (Silero VAD model, its audio worklet and
// the ONNX runtime) to public/vad/, so they are served by our own site, not a CDN.
// Runs before `npm run dev` and `npm run build`.
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "public", "vad");
const files = [
  "node_modules/@ricky0123/vad-web/dist/vad.worklet.bundle.min.js",
  "node_modules/@ricky0123/vad-web/dist/silero_vad_v5.onnx",
  "node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.wasm",
  "node_modules/onnxruntime-web/dist/ort-wasm-simd-threaded.mjs",
];

mkdirSync(out, { recursive: true });
for (const file of files) {
  copyFileSync(join(root, file), join(out, file.split("/").pop()));
}
console.log(`VAD: ${files.length} archivos copiados a public/vad/`);
