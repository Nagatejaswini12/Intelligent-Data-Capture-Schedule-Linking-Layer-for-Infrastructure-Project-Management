// On-device AI: a small ONNX model from Hugging Face runs in the browser on the user's GPU (WebGPU). No server GPU and
// no outside account. It only rephrases the server's verified answer: the server sends the guard-railed prompt (scope
// rules + facts), and `guard` below repeats the server's checks before anything is shown. Any failure -> rules answer.
type Msg = { role: "system" | "user"; content: string };

export const MODEL = "onnx-community/Qwen3.5-0.8B-Text-ONNX";   // Apache-2.0 (Qwen/Qwen3.5-0.8B), 201 languages, ≈470 MB q4f16
export const MODEL_LABEL = "Qwen3.5-0.8B · on-device";
export const webgpuAvailable = () => typeof navigator !== "undefined" && "gpu" in navigator;

const NUM = /\p{Nd}+(?:[.,]\p{Nd}+)*/gu;
const nums = (s: string) => new Set((s.match(NUM) ?? []).map((n) => n.replace(/,/g, "")));

/** The model's text if it is in scope, every number in it appears in the prompt's facts/question, and it keeps every
 *  number of the verified answer (a small model may otherwise drop the facts and answer vaguely), else null. */
export function guard(text: string, prompt: Msg[], verified = ""): string | null {
  const t = text.replace(/<think>[\s\S]*?<\/think>/g, "").trim();
  if (!t || t.includes("OUT_OF_SCOPE")) return null;
  const known = nums(prompt.map((m) => m.content).join(" ")), got = nums(t);
  return [...got].every((n) => known.has(n)) && [...nums(verified)].every((n) => got.has(n)) ? t : null;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
let loading: Promise<any> | null = null;

/** Downloads (first time; then browser-cached) and starts the model. onProgress gets 0..100. */
export function load(onProgress?: (pct: number) => void) {
  loading ??= import("@huggingface/transformers").then(({ env, pipeline }) => {
    // everything from our own site: the ONNX Runtime engine (copied into /ort at build) and, when VITE_MODEL_HOST is
    // set (Vercel Blob mirror, see web/scripts/mirror-model.mjs), the model files; otherwise the model comes from Hugging Face
    if (env.backends.onnx.wasm) env.backends.onnx.wasm.wasmPaths =
      { mjs: "/ort/ort-wasm-simd-threaded.asyncify.mjs", wasm: "/ort/ort-wasm-simd-threaded.asyncify.wasm" };
    const host = import.meta.env.VITE_MODEL_HOST as string | undefined;
    if (host) { env.remoteHost = host.endsWith("/") ? host : host + "/"; env.remotePathTemplate = "{model}/"; }
    const files: Record<string, [number, number]> = {};
    return pipeline("text-generation", MODEL, {
      device: "webgpu", dtype: "q4f16",
      progress_callback: (p: { status: string; file?: string; loaded?: number; total?: number }) => {
        if (p.status !== "progress" || !p.file || !p.total) return;
        files[p.file] = [p.loaded ?? 0, p.total];
        const [l, tot] = Object.values(files).reduce(([a, b], [x, y]) => [a + x, b + y], [0, 0]);
        onProgress?.(Math.round((100 * l) / tot));
      },
    });
  }).catch((e) => { loading = null; throw e; });
  return loading;
}

/** Rephrased answer, or null (no WebGPU, model failed, or the answer failed the guard). */
export async function rephrase(prompt: Msg[], verified: string, onProgress?: (pct: number) => void): Promise<string | null> {
  if (!webgpuAvailable()) return null;
  try {
    const gen = await load(onProgress);
    const text = gen.tokenizer.apply_chat_template(prompt, { tokenize: false, add_generation_prompt: true, enable_thinking: false });
    const [out] = await gen(text, { max_new_tokens: 350, do_sample: false, return_full_text: false });
    return guard(out.generated_text as string, prompt, verified);
  } catch {
    return null;
  }
}
