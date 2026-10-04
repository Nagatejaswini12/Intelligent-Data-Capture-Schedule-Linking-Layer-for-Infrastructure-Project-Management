// Copy the on-device model from Hugging Face into your Vercel Blob store (public), once, so users download it from
// Vercel and the app needs no other service. Then set VITE_MODEL_HOST=<printed host> in Vercel and redeploy.
//   set BLOB_READ_WRITE_TOKEN=<token of a PUBLIC Blob store>   &&   node scripts/mirror-model.mjs
import { put } from "@vercel/blob";

const MODEL = "onnx-community/Qwen3.5-0.8B-Text-ONNX";        // keep in sync with src/utils/localAi.ts
const FILES = ["config.json", "generation_config.json", "tokenizer.json", "tokenizer_config.json", "chat_template.jinja",
  "onnx/model_q4f16.onnx", "onnx/model_q4f16.onnx_data"];

let host = "";
for (const f of FILES) {
  const res = await fetch(`https://huggingface.co/${MODEL}/resolve/main/${f}`);
  if (!res.ok) throw new Error(`${f}: HTTP ${res.status}`);
  const blob = await put(`models/${MODEL}/${f}`, Buffer.from(await res.arrayBuffer()),
    { access: "public", addRandomSuffix: false, allowOverwrite: true, multipart: true });
  host = blob.url.slice(0, blob.url.indexOf(`/models/`) + "/models/".length);
  console.log("uploaded", f);
}
console.log(`\nSet in Vercel -> Settings -> Environment Variables:\n  VITE_MODEL_HOST=${host}`);
