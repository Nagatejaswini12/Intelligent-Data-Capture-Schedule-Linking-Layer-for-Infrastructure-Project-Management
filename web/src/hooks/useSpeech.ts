import { useEffect, useRef, useState } from "react";
import { p2e } from "../api/p2e";

// Voice for the Time Agent and the assistant. Uses BHASHINI (Government of India language AI, through our server so keys
// never reach the browser) when the server has it configured, including Assamese; otherwise the browser's speech engine.
export type VoiceLang = "en" | "hi" | "ta" | "as";
const BCP47: Record<VoiceLang, string> = { en: "en-IN", hi: "hi-IN", ta: "ta-IN", as: "as-IN" };

type Recognizer = { lang: string; interimResults: boolean; onresult: (e: { results: { 0: { transcript: string } }[] }) => void;
  onend: () => void; onerror: () => void; start: () => void };
const g = globalThis as unknown as { SpeechRecognition?: new () => Recognizer; webkitSpeechRecognition?: new () => Recognizer };
const BrowserRec = g.SpeechRecognition ?? g.webkitSpeechRecognition;

let statusPromise: Promise<{ provider: string; languages: string[] }> | null = null;

/** 16-bit PCM mono WAV at 16 kHz, base64 — the format BHASHINI ASR accepts. */
async function toWav16k(blob: Blob): Promise<string> {
  const ctx = new AudioContext();
  const decoded = await ctx.decodeAudioData(await blob.arrayBuffer());
  await ctx.close();
  const frames = Math.ceil(decoded.duration * 16000);
  const off = new OfflineAudioContext(1, frames, 16000);
  const src = off.createBufferSource();
  src.buffer = decoded;
  src.connect(off.destination);
  src.start();
  const pcm = (await off.startRendering()).getChannelData(0);
  const buf = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const str = (o: number, s: string) => [...s].forEach((c, i) => buf.setUint8(o + i, c.charCodeAt(0)));
  str(0, "RIFF"); buf.setUint32(4, 36 + pcm.length * 2, true); str(8, "WAVEfmt "); buf.setUint32(16, 16, true);
  buf.setUint16(20, 1, true); buf.setUint16(22, 1, true); buf.setUint32(24, 16000, true); buf.setUint32(28, 32000, true);
  buf.setUint16(32, 2, true); buf.setUint16(34, 16, true); str(36, "data"); buf.setUint32(40, pcm.length * 2, true);
  pcm.forEach((v, i) => buf.setInt16(44 + i * 2, Math.max(-1, Math.min(1, v)) * 0x7fff, true));
  let bin = "";
  new Uint8Array(buf.buffer).forEach((b) => { bin += String.fromCharCode(b); });
  return btoa(bin);
}

export function useSpeech() {
  const [provider, setProvider] = useState<"bhashini" | "browser" | "none">(BrowserRec ? "browser" : "none");
  const [listening, setListening] = useState(false);
  const rec = useRef<MediaRecorder | null>(null);

  useEffect(() => {
    statusPromise ??= p2e.speechStatus().catch(() => ({ provider: "browser", languages: [] }));
    statusPromise.then((s) => { if (s.provider === "bhashini") setProvider("bhashini"); });
  }, []);

  const languages: VoiceLang[] = provider === "bhashini" ? ["en", "hi", "ta", "as"] : ["en", "hi", "ta"];

  /** Start listening; resolves with the transcript. With BHASHINI, call stop() (or wait 12 s) to finish recording. */
  const listen = (lang: VoiceLang): Promise<string> => new Promise((resolve, reject) => {
    if (provider === "bhashini") {
      navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
        const chunks: Blob[] = [];
        const mr = new MediaRecorder(stream);
        rec.current = mr;
        mr.ondataavailable = (e) => chunks.push(e.data);
        mr.onstop = async () => {
          stream.getTracks().forEach((tr) => tr.stop());
          setListening(false);
          try {
            const audio = await toWav16k(new Blob(chunks, { type: mr.mimeType }));
            resolve((await p2e.asr({ audio_b64: audio, lang })).text);
          } catch (e) { reject(e); }
        };
        setListening(true);
        mr.start();
        setTimeout(() => { if (mr.state === "recording") mr.stop(); }, 12000);
      }, reject);
      return;
    }
    if (!BrowserRec) { reject(new Error("Voice input is not available in this browser")); return; }
    const r = new BrowserRec();
    r.lang = BCP47[lang];
    r.interimResults = false;
    r.onresult = (e) => resolve(e.results[0][0].transcript);
    r.onend = r.onerror = () => setListening(false);
    setListening(true);
    r.start();
  });

  const stop = () => { if (rec.current?.state === "recording") rec.current.stop(); };

  /** Read text aloud: BHASHINI TTS when configured (all four languages), else an installed browser voice.
   *  Resolves false when this device has no voice for the language (Windows: add the language's speech pack, or use Edge). */
  const speak = async (text: string, lang: VoiceLang): Promise<boolean> => {
    if (provider === "bhashini") {
      try {
        const { audio_b64 } = await p2e.tts({ text: text.slice(0, 1500), lang });
        await new Audio(`data:audio/wav;base64,${audio_b64}`).play();
        return true;
      } catch { /* fall back to the browser voice */ }
    }
    if (!("speechSynthesis" in globalThis)) return false;
    const voices = speechSynthesis.getVoices().length ? speechSynthesis.getVoices()
      : await new Promise<SpeechSynthesisVoice[]>((r) => { speechSynthesis.onvoiceschanged = () => r(speechSynthesis.getVoices()); setTimeout(() => r(speechSynthesis.getVoices()), 1500); });
    const voice = voices.find((v) => v.lang === BCP47[lang]) ?? voices.find((v) => v.lang.toLowerCase().startsWith(lang));
    if (!voice) return false;
    const u = new SpeechSynthesisUtterance(text);
    u.voice = voice;
    u.lang = voice.lang;
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
    return true;
  };

  const translate = async (text: string, source: VoiceLang, target: VoiceLang) =>
    source === target || provider !== "bhashini" ? text : (await p2e.translate({ text, source, target })).text;

  return { provider, languages, listening, listen, stop, speak, translate };
}
