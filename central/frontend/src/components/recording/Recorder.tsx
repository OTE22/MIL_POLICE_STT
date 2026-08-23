import { useCallback, useEffect, useRef, useState } from "react";

import { formatBytes, formatClock } from "@/lib/format";
import { T } from "@/lib/i18n";
import { IconFile, IconMic, IconPause, IconPlay, IconStop, IconUpload, IconX } from "@/components/Icons";

export interface PendingAudio {
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
  onReady,
}: {
  disabled: boolean;
  onReady: (audio: PendingAudio | null) => void;
}) {
  const [mic, setMic] = useState<MicState>("idle");
  const [rec, setRec] = useState<RecState>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [level, setLevel] = useState(0);
  const [pending, setPending] = useState<PendingAudio | null>(null);
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

  useEffect(() => () => releaseStream(), [releaseStream]);

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
    setPending(null);
    onReady(null);
    setMic("requesting");
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 } });
    } catch (e) {
      setMic(e instanceof DOMException && e.name === "NotAllowedError" ? "denied" : "unavailable");
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
      setPending(audio);
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
      setPending({ ...audio });
      onReady({ ...audio });
    };
    el.onerror = () => {
      URL.revokeObjectURL(url);
      setPending(audio);
      onReady(audio);
    };
    el.src = url;
    setRec("idle");
    setPending(audio);
    onReady(audio);
  };

  const discard = () => {
    setPending(null);
    onReady(null);
    setRec("idle");
    setElapsed(0);
    if (fileInput.current) fileInput.current.value = "";
  };

  const micLabel =
    mic === "ready" ? T.micReady : mic === "requesting" ? T.micRequesting : mic === "denied" ? T.micDenied : mic === "unavailable" ? T.micUnavailable : T.notAvailable;
  const recLabel = rec === "live" ? T.recLive : rec === "paused" ? T.recPaused : rec === "stopped" ? T.recStopped : T.recIdle;

  return (
    <div className="card">
      <div className="card-header">
        <h3>{T.tabRecording}</h3>
        <div className="rec-indicator">
          <span className={`rec-dot ${rec === "live" ? "live" : rec === "paused" ? "paused" : ""}`} />
          {recLabel}
        </div>
      </div>
      <div className="card-body">
        <div className="status-list">
          <div className="status-row">
            <span className="k">{T.microphoneStatus}</span>
            <span>{micLabel}</span>
          </div>
          <div className="status-row">
            <span className="k">{T.recordingStatus}</span>
            <span>{recLabel}</span>
          </div>
        </div>
        <div className="rec-timer num" aria-live="off">
          {formatClock(elapsed)}
        </div>
        <div className="level-meter" aria-hidden>
          <span style={{ width: `${Math.round(level * 100)}%` }} />
        </div>
        <div className="rec-controls">
          {(rec === "idle" || rec === "stopped") && (
            <button className="btn btn-danger btn-lg" onClick={() => void start()} disabled={disabled || !!pending} type="button">
              <IconMic /> {T.startRecording}
            </button>
          )}
          {rec === "live" && (
            <button className="btn btn-lg" onClick={pause} type="button">
              <IconPause /> {T.pauseRecording}
            </button>
          )}
          {rec === "paused" && (
            <button className="btn btn-lg" onClick={resume} type="button">
              <IconPlay /> {T.resumeRecording}
            </button>
          )}
          {(rec === "live" || rec === "paused") && (
            <button className="btn btn-primary btn-lg" onClick={stop} type="button">
              <IconStop /> {T.stopRecording}
            </button>
          )}
          {(rec === "idle" || rec === "stopped") && (
            <button className="btn btn-lg" onClick={() => fileInput.current?.click()} disabled={disabled || !!pending} type="button">
              <IconUpload /> {T.uploadAudio}
            </button>
          )}
          <input ref={fileInput} type="file" accept={ACCEPT} className="sr-only" onChange={(e) => e.target.files?.[0] && acceptFile(e.target.files[0])} />
        </div>

        {!pending && rec !== "live" && rec !== "paused" && (
          <div
            className={`dropzone mt-16 ${dragOver ? "over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const f = e.dataTransfer.files?.[0];
              if (f) acceptFile(f);
            }}
            onClick={() => fileInput.current?.click()}
            role="button"
            tabIndex={0}
          >
            {T.dropHint}
          </div>
        )}
        {fileError && <div className="error-text mt-8">{fileError}</div>}
        {pending && (
          <div className="mt-16 flex between wrap">
            <span className="file-chip">
              <IconFile width={16} height={16} />
              <span className="ltr">{pending.filename}</span>
              <span className="muted">({formatBytes(pending.blob.size)}{pending.durationSeconds ? ` — ${formatClock(pending.durationSeconds)}` : ""})</span>
            </span>
            <button className="btn btn-sm btn-ghost" onClick={discard} type="button" disabled={disabled}>
              <IconX /> {T.discard}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
