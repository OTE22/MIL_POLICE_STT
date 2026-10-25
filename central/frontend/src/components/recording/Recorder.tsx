import { useCallback, useEffect, useRef, useState } from "react";

import { formatBytes, formatClock } from "@/lib/format";
import { T } from "@/lib/i18n";
import { IconCheck, IconMic, IconPause, IconPlay, IconStop, IconUpload, IconX } from "@/components/Icons";

export interface PendingAudio {
  recordingId?: string;
  sessionId?: string;
  blob: Blob;
  filename: string;
  mimeType: string;
  source: "BROWSER_RECORDING" | "FILE_UPLOAD";
  durationSeconds: number | null;
}

type MicState = "idle" | "requesting" | "ready" | "denied" | "unavailable";
type RecState = "idle" | "live" | "paused" | "stopped";

const ACCEPT = ".wav,.mp3,.m4a,.webm,audio/wav,audio/x-wav,audio/mpeg,audio/mp4,audio/x-m4a,audio/webm";
const MAX_BYTES = 2 * 1024 * 1024 * 1024;

function pickMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  for (const c of candidates) if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(c)) return c;
  return "";
}

export function Recorder({
  disabled,
  pending,
  onReady,
}: {
  disabled: boolean;
  pending: PendingAudio | null;
  onReady: (audio: PendingAudio | null) => void;
}) {
  const [mic, setMic] = useState<MicState>("idle");
  const [rec, setRec] = useState<RecState>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [source, setSource] = useState<"file" | "microphone">(pending?.source === "BROWSER_RECORDING" ? "microphone" : "file");
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const startedAt = useRef<number>(0);
  const accumulated = useRef<number>(0);
  const tickRef = useRef<number | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const selectionVersion = useRef(0);

  useEffect(() => {
    if (pending) setSource(pending.source === "BROWSER_RECORDING" ? "microphone" : "file");
  }, [pending?.source]);

  useEffect(() => {
    if (!pending) { setPreviewUrl(null); return; }
    const url = URL.createObjectURL(pending.blob);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [pending?.blob]);

  const stopMeter = () => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    rafRef.current = null;
    if (audioCtxRef.current) void audioCtxRef.current.close().catch(() => undefined);
    audioCtxRef.current = null;
    setLevel(0);
  };

  const releaseStream = useCallback(() => {
    stopMeter();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => () => {
    selectionVersion.current += 1;
    if (tickRef.current) window.clearInterval(tickRef.current);
    const activeRecorder = recorderRef.current;
    if (activeRecorder && activeRecorder.state !== "inactive") {
      if (activeRecorder.state === "recording") accumulated.current += (Date.now() - startedAt.current) / 1000;
      // Finishing on tab exit preserves the captured audio in the parent workspace.
      activeRecorder.stop();
    }
    releaseStream();
  }, [releaseStream]);

  const startMeter = (stream: MediaStream) => {
    try {
      const ctx = new AudioContext();
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 512;
      src.connect(analyser);
      const data = new Uint8Array(analyser.frequencyBinCount);
      audioCtxRef.current = ctx;
      const loop = () => {
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) {
          const v = (data[i] - 128) / 128;
          sum += v * v;
        }
        setLevel(Math.min(1, Math.sqrt(sum / data.length) * 3));
        rafRef.current = requestAnimationFrame(loop);
      };
      loop();
    } catch {
      /* meter is cosmetic */
    }
  };

  const tick = () => setElapsed(accumulated.current + (Date.now() - startedAt.current) / 1000);

  const start = async () => {
    setFileError(null);
    onReady(null);
    setMic("requesting");
    const captureVersion = selectionVersion.current;
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
    } catch (e) {
      setMic(e instanceof DOMException && e.name === "NotAllowedError" ? "denied" : "unavailable");
      return;
    }
    if (captureVersion !== selectionVersion.current) {
      stream.getTracks().forEach(track => track.stop());
      return;
    }
    streamRef.current = stream;
    setMic("ready");
    startMeter(stream);
    const mimeType = pickMimeType();
    const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    chunksRef.current = [];
    recorder.ondataavailable = (ev) => {
      if (ev.data.size > 0) chunksRef.current.push(ev.data);
    };
    recorder.onstop = () => {
      const type = recorder.mimeType || mimeType || "audio/webm";
      const blob = new Blob(chunksRef.current, { type });
      const ext = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "webm" : "webm";
      const duration = accumulated.current;
      const audio: PendingAudio = {
        blob,
        filename: `recording-${new Date().toISOString().replace(/[:.]/g, "-")}.${ext}`,
        mimeType: type.split(";")[0],
        source: "BROWSER_RECORDING",
        durationSeconds: duration,
      };
      onReady(audio);
      releaseStream();
    };
    recorderRef.current = recorder;
    accumulated.current = 0;
    startedAt.current = Date.now();
    setElapsed(0);
    recorder.start(1000);
    setRec("live");
    tickRef.current = window.setInterval(tick, 250);
  };

  const pause = () => {
    recorderRef.current?.pause();
    accumulated.current += (Date.now() - startedAt.current) / 1000;
    if (tickRef.current) window.clearInterval(tickRef.current);
    setRec("paused");
  };
  const resume = () => {
    recorderRef.current?.resume();
    startedAt.current = Date.now();
    tickRef.current = window.setInterval(tick, 250);
    setRec("live");
  };
  const stop = () => {
    if (rec === "live") accumulated.current += (Date.now() - startedAt.current) / 1000;
    if (tickRef.current) window.clearInterval(tickRef.current);
    setElapsed(accumulated.current);
    recorderRef.current?.stop();
    setRec("stopped");
  };

  const acceptFile = (file: File) => {
    if (disabled || rec === "live" || rec === "paused" || mic === "requesting") return;
    setFileError(null);
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
    if (!["wav", "mp3", "m4a", "webm"].includes(ext)) {
      setFileError(T.unsupportedAudio);
      return;
    }
    if (file.size === 0) {
      setFileError(T.err_empty_file);
      return;
    }
    if (file.size > MAX_BYTES) {
      setFileError(T.audioTooLarge);
      return;
    }
    const version = ++selectionVersion.current;
    const audio: PendingAudio = {
      blob: file,
      filename: file.name,
      mimeType: file.type || (ext === "wav" ? "audio/wav" : ext === "mp3" ? "audio/mpeg" : ext === "m4a" ? "audio/mp4" : "audio/webm"),
      source: "FILE_UPLOAD",
      durationSeconds: null,
    };
    // Read the duration client-side (best effort; the Local Agent is authoritative).
    const url = URL.createObjectURL(file);
    const el = document.createElement("audio");
    el.preload = "metadata";
    el.onloadedmetadata = () => {
      audio.durationSeconds = Number.isFinite(el.duration) ? el.duration : null;
      URL.revokeObjectURL(url);
      if (version === selectionVersion.current) onReady({ ...audio });
    };
    el.onerror = () => {
      URL.revokeObjectURL(url);
      if (version === selectionVersion.current) onReady(audio);
    };
    el.src = url;
    setRec("idle");
    onReady(audio);
  };

  const discard = () => {
    selectionVersion.current += 1;
    onReady(null);
    setRec("idle");
    setElapsed(0);
    if (fileInput.current) fileInput.current.value = "";
  };

  const micLabel =
    mic === "ready" ? T.micReady : mic === "requesting" ? T.micRequesting : mic === "denied" ? T.micDenied : mic === "unavailable" ? T.micUnavailable : T.notAvailable;
  const recLabel = rec === "live" ? T.recLive : rec === "paused" ? T.recPaused : rec === "stopped" ? T.recStopped : T.recIdle;

  const capturing = rec === "live" || rec === "paused" || mic === "requesting";
  return <section className="card recording-source-card" data-testid="recording-source">
    <div className="card-header"><div><h3>١. اختر مصدر التسجيل</h3><p className="workspace-section-hint">ارفع ملفاً صوتياً أو سجّل مباشرة من الميكروفون.</p></div>
      {source === "microphone" && <span className="rec-indicator" role="status"><span className={`rec-dot ${rec === "live" ? "live" : rec === "paused" ? "paused" : ""}`} />{recLabel}</span>}
    </div>
    <div className="card-body">
      <div className="recorder-source-choice" aria-label="مصدر التسجيل">
        <button type="button" aria-pressed={source === "file"} disabled={disabled || capturing || !!pending} onClick={() => { setSource("file"); setFileError(null); }}><IconUpload /><span><strong>رفع ملف صوتي</strong><span>اختر تسجيلاً محفوظاً على جهازك</span></span></button>
        <button type="button" aria-pressed={source === "microphone"} disabled={disabled || capturing || !!pending} onClick={() => { setSource("microphone"); setFileError(null); }}><IconMic /><span><strong>تسجيل مباشر</strong><span>استخدم ميكروفون هذا الجهاز</span></span></button>
      </div>
      <input ref={fileInput} type="file" accept={ACCEPT} aria-label="اختيار ملف صوتي" className="sr-only" disabled={disabled || capturing} onChange={e => e.target.files?.[0] && acceptFile(e.target.files[0])} />
      {!pending && source === "file" && <button type="button" className={`dropzone ${dragOver ? "over" : ""}`} disabled={disabled}
        onDragOver={e => { e.preventDefault(); if (!disabled) setDragOver(true); }} onDragLeave={() => setDragOver(false)}
        onDrop={e => { e.preventDefault(); setDragOver(false); const file = e.dataTransfer.files?.[0]; if (file && !disabled) acceptFile(file); }}
        onClick={() => fileInput.current?.click()} data-testid="audio-dropzone"><IconUpload /><strong>اسحب الملف إلى هنا أو انقر لاختياره</strong><span>WAV · MP3 · M4A · WebM</span><span>الحد الأقصى لحجم الملف: ٢ غيغابايت</span></button>}
      {!pending && source === "microphone" && <div className="recording-microphone">
        <div className="rec-timer num" aria-live="off">{formatClock(elapsed)}</div>
        <div className="level-meter" aria-hidden><span style={{ width: `${Math.round(level * 100)}%` }} /></div>
        <div className="rec-controls">
          {(rec === "idle" || rec === "stopped") && <button className="btn btn-primary btn-lg" type="button" disabled={disabled || mic === "requesting"} onClick={() => void start()}><IconMic />{mic === "requesting" ? T.micRequesting : T.startRecording}</button>}
          {rec === "live" && <button className="btn btn-lg" type="button" onClick={pause}><IconPause />{T.pauseRecording}</button>}
          {rec === "paused" && <button className="btn btn-lg" type="button" onClick={resume}><IconPlay />{T.resumeRecording}</button>}
          {(rec === "live" || rec === "paused") && <button className="btn btn-danger btn-lg" type="button" onClick={stop}><IconStop />{T.stopRecording}</button>}
        </div>
        <div className="status-list"><div className="status-row"><span className="k">{T.microphoneStatus}</span><span role="status">{mic === "idle" ? "يُطلب الإذن عند بدء التسجيل" : micLabel}</span></div></div>
        <p className="workspace-section-hint">عند مغادرة هذا التبويب، ينتهي التسجيل ويُحتفظ بالصوت هنا بانتظار المعالجة.</p>
      </div>}
      {fileError && <div className="error-text mt-16" role="alert">{fileError}</div>}
      {pending && <><div className="recording-selection" data-testid="pending-audio"><IconCheck /><div><strong>التسجيل جاهز للمعالجة</strong><p><bdi>{pending.filename}</bdi></p><p>{formatBytes(pending.blob.size)}{pending.durationSeconds ? ` · ${formatClock(pending.durationSeconds)}` : ""}</p><p>راجع الصوت، ثم اضغط «{T.processRecording}» في الخطوة التالية.</p></div>
        <button className="btn btn-sm btn-ghost" type="button" disabled={disabled} onClick={discard}><IconX />{T.discard}</button></div>
        {previewUrl && <audio className="recording-preview" src={previewUrl} controls preload="metadata" aria-label="معاينة التسجيل قبل المعالجة" />}
      </>}
    </div>
  </section>;
}
