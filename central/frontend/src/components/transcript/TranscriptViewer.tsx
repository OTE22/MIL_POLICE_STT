import { useEffect, useMemo, useRef, useState } from "react";

import { ApiError, fetchBlobUrl, http } from "@/api/client";
import type { Segment, Speaker, Transcript } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatClock, formatDateTime, speakerColor } from "@/lib/format";
import { T, errorMessage, t } from "@/lib/i18n";
import { Alert, Badge, useToast } from "@/components/ui";
import { IconEdit, IconPlay, IconSearch } from "@/components/Icons";

function speakerName(label: string, speakers: Speaker[]): string {
  const s = speakers.find((x) => x.speaker_label === label);
  if (s?.display_name) return s.display_name;
  if (s && s.speaker_role !== "UNKNOWN") return t(`role_${s.speaker_role}`);
  return label;
}

function Highlight({ text, query }: { text: string; query: string }) {
  if (!query) return <>{text}</>;
  const parts = text.split(new RegExp(`(${query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "gi"));
  return (
    <>
      {parts.map((p, i) => (p.toLowerCase() === query.toLowerCase() ? <mark key={i}>{p}</mark> : <span key={i}>{p}</span>))}
    </>
  );
}

function SegmentRow({
  seg,
  speakers,
  active,
  query,
  canEdit,
  onSeek,
  onSaved,
}: {
  seg: Segment;
  speakers: Speaker[];
  active: boolean;
  query: string;
  canEdit: boolean;
  onSeek: (s: number) => void;
  onSaved: (s: Segment) => void;
}) {
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(seg.edited_text ?? seg.original_text);
  const [busy, setBusy] = useState(false);
  const text = seg.edited_text ?? seg.original_text;

  const save = async (value: string) => {
    setBusy(true);
    try {
      const updated = await http.patch<Segment>(`/transcript-segments/${seg.id}`, { edited_text: value });
      onSaved(updated);
      setEditing(false);
      toast.success(T.segmentSaved);
    } catch (err) {
      toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`segment ${active ? "active" : ""}`} onClick={() => !editing && onSeek(seg.start_seconds)} data-testid="segment" data-sequence={seg.sequence}>
      <div className="who">
        <span className="speaker">
          <span className="sw" style={{ background: speakerColor(seg.speaker_label) }} />
          {speakerName(seg.speaker_label, speakers)}
        </span>
        <span className="time num">
          {formatClock(seg.start_seconds)} - {formatClock(seg.end_seconds)}
        </span>
        <span className="small muted ltr">{seg.speaker_label}</span>
      </div>
      <div>
        {editing ? (
          <div className="edit-area" onClick={(e) => e.stopPropagation()}>
            <textarea className="textarea" value={draft} onChange={(e) => setDraft(e.target.value)} autoFocus />
            <div className="orig-box">
              <b>{T.original} ({T.aiResult})</b>
              {seg.original_text}
            </div>
            <div className="flex">
              <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => void save(draft)} type="button">
                {T.saveEdit}
              </button>
              {seg.edited_text && (
                <button className="btn btn-sm" disabled={busy} onClick={() => void save(seg.original_text)} type="button">
                  {T.restoreOriginal}
                </button>
              )}
              <button className="btn btn-ghost btn-sm" onClick={() => { setEditing(false); setDraft(text); }} type="button">
                {T.cancel}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="text" lang="ar">
              <Highlight text={text} query={query} />
            </div>
            <div className="tags">
              {seg.edited_text ? (
                <Badge kind="amber">
                  {T.edited}
                  {seg.edited_by_name ? ` — ${seg.edited_by_name}` : ""}
                  {seg.edited_at ? ` — ${formatDateTime(seg.edited_at)}` : ""}
                </Badge>
              ) : (
                <Badge kind="gray">{T.aiResult}</Badge>
              )}
              {seg.is_overlap && <Badge kind="red">{T.overlap}</Badge>}
              {seg.confidence != null && <span className="small muted num">{Math.round(seg.confidence * 100)}%</span>}
            </div>
            {seg.edited_text && (
              <div className="orig-box mt-8">
                <b>{T.original}</b>
                {seg.original_text}
              </div>
            )}
          </>
        )}
      </div>
      <div className="tools" onClick={(e) => e.stopPropagation()}>
        <button className="icon-btn" title={T.playFrom} onClick={() => onSeek(seg.start_seconds)} type="button">
          <IconPlay />
        </button>
        {canEdit && !editing && (
          <button className="icon-btn" title={T.editText} onClick={() => setEditing(true)} type="button" data-testid="edit-segment">
            <IconEdit />
          </button>
        )}
      </div>
    </div>
  );
}

export function TranscriptViewer({ transcript, onChange }: { transcript: Transcript; onChange: (tr: Transcript) => void }) {
  const { can } = useAuth();
  const [query, setQuery] = useState("");
  const [speakerFilter, setSpeakerFilter] = useState("");
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioError, setAudioError] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    let url: string | null = null;
    if (transcript.audio_available) {
      fetchBlobUrl(`/recordings/${transcript.recording_id}/audio`)
        .then((u) => {
          url = u;
          setAudioUrl(u);
        })
        .catch(() => setAudioError(true));
    }
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [transcript.recording_id, transcript.audio_available]);

  const visible = useMemo(
    () =>
      transcript.segments.filter(
        (s) => (!speakerFilter || s.speaker_label === speakerFilter) && (!query || (s.edited_text ?? s.original_text).includes(query)),
      ),
    [transcript.segments, speakerFilter, query],
  );

  const activeId = useMemo(() => {
    const seg = transcript.segments.find((s) => currentTime >= s.start_seconds && currentTime < s.end_seconds);
    return seg?.id ?? null;
  }, [currentTime, transcript.segments]);

  const seek = (seconds: number) => {
    const el = audioRef.current;
    if (!el) return;
    el.currentTime = seconds;
    void el.play().catch(() => undefined);
    setCurrentTime(seconds);
  };

  const onSaved = (updated: Segment) =>
    onChange({ ...transcript, segments: transcript.segments.map((s) => (s.id === updated.id ? updated : s)) });

  return (
    <div className="transcript-layout">
      <div className="card" data-testid="transcript">
        <div className="transcript-toolbar">
          <div className="flex" style={{ position: "relative", flex: 1 }}>
            <input className="input" placeholder={T.searchTranscript} value={query} onChange={(e) => setQuery(e.target.value)} aria-label={T.searchTranscript} />
            <IconSearch style={{ position: "absolute", insetInlineEnd: 10, top: 9, color: "var(--muted)" }} width={16} height={16} />
          </div>
          <select className="select" value={speakerFilter} onChange={(e) => setSpeakerFilter(e.target.value)} aria-label={T.speakerFilter}>
            <option value="">{T.allSpeakers}</option>
            {transcript.speakers.map((s) => (
              <option key={s.id} value={s.speaker_label}>
                {speakerName(s.speaker_label, transcript.speakers)}
              </option>
            ))}
          </select>
          <span className="muted small">
            {T.segments}: <span className="num">{visible.length}</span> / <span className="num">{transcript.segments.length}</span>
          </span>
        </div>
        <div className="player">
          {audioUrl ? (
            <audio ref={audioRef} src={audioUrl} controls preload="metadata" onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)} data-testid="audio-player" />
          ) : audioError || !transcript.audio_available ? (
            <Alert kind="info">{T.audioUnavailable}</Alert>
          ) : (
            <span className="muted small">{T.loading}</span>
          )}
          <div className="ptime num">
            <span>{formatClock(currentTime)}</span>
          </div>
        </div>
        <div className="segments">
          {visible.length === 0 && <div className="center muted" style={{ padding: 30 }}>{T.noData}</div>}
          {visible.map((seg) => (
            <SegmentRow key={seg.id} seg={seg} speakers={transcript.speakers} active={seg.id === activeId} query={query} canEdit={can("transcripts.edit")} onSeek={seek} onSaved={onSaved} />
          ))}
        </div>
      </div>

      <aside>
        <div className="card">
          <div className="card-header">
            <h3>{T.modelsUsed}</h3>
          </div>
          <div className="card-body">
            <dl className="dl" style={{ gridTemplateColumns: "1fr" }}>
              <div>
                <dt>{T.sttModel}</dt>
                <dd className="ltr small">{transcript.stt_model ?? T.none}</dd>
                <dd className="muted small ltr">{transcript.stt_model_revision ?? ""}</dd>
              </div>
              <div>
                <dt>{T.diarModel}</dt>
                <dd className="ltr small">{transcript.diarization_model ?? T.none}</dd>
                <dd className="muted small ltr">{transcript.diarization_model_revision ?? ""}</dd>
              </div>
              <div>
                <dt>{T.vadModel}</dt>
                <dd className="ltr small">{transcript.vad_model ?? T.none}</dd>
              </div>
              <div>
                <dt>{T.agentVersion}</dt>
                <dd className="ltr small">{transcript.agent_version ?? T.none}</dd>
              </div>
              <div>
                <dt>{T.processingDevice}</dt>
                <dd className="ltr small">{transcript.processing_device ?? T.none}</dd>
              </div>
              <div>
                <dt>{T.speakerCount}</dt>
                <dd className="num">{transcript.speaker_count ?? T.none}</dd>
              </div>
              <div>
                <dt>{T.receivedAt}</dt>
                <dd className="num">{formatDateTime(transcript.created_at)}</dd>
              </div>
            </dl>
            {transcript.warnings.length > 0 && (
              <div className="mt-16">
                <Alert kind="warning">
                  <b>{T.warnings}</b>
                  <ul style={{ margin: "4px 0 0", paddingInlineStart: 18 }}>
                    {transcript.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </Alert>
              </div>
            )}
          </div>
        </div>
      </aside>
    </div>
  );
}
