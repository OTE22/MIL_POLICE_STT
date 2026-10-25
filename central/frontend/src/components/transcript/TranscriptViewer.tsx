import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, fetchBlobUrl, http } from "@/api/client";
import type { Segment, Speaker, Transcript } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatClock, formatDateTime, formatTimestamp, speakerColor } from "@/lib/format";
import { T, errorMessage, t } from "@/lib/i18n";
import { Alert, Badge, useToast } from "@/components/ui";
import { IconEdit, IconPlay, IconSearch, IconFile, IconUsers, IconChevronLeft, IconWave } from "@/components/Icons";
import { transcriptSpeakerOptions } from "@/lib/transcript-speakers";
import { groupTranscriptTurns, type TranscriptTurn } from "@/lib/transcript-turns";
import "@/styles/transcript-workspace.css";

function speakerName(label: string, speakers: Speaker[]): string {
  const s = speakers.find((x) => x.speaker_label === label);
  if (s?.identity_name || s?.display_name) return s.identity_name || s.display_name!;
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
  active,
  query,
  canEdit,
  canPlay,
  onSeek,
  onSaved,
}: {
  seg: Segment;
  active: boolean;
  query: string;
  canEdit: boolean;
  canPlay: boolean;
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
    <div className={`segment ${active ? "active" : ""}`} onClick={() => !editing && canPlay && onSeek(seg.start_seconds)} data-testid="segment" data-sequence={seg.sequence}>
      <div className="who">
        <span className="time num">
          {formatTimestamp(seg.start_seconds)} - {formatTimestamp(seg.end_seconds)}
        </span>
      </div>
      <div className="segment-content">
        {editing ? (
          <div className="edit-area" onClick={(e) => e.stopPropagation()}>
            <textarea className="textarea" aria-label="تعديل نص المقطع" value={draft} onChange={(e) => setDraft(e.target.value)} disabled={busy} autoFocus />
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
              <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => { setEditing(false); setDraft(text); }} type="button">
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
              <details className="transcript-original"><summary>مقارنة مع النص الأصلي</summary><div className="orig-box mt-8"><b>{T.original}</b>{seg.original_text}</div></details>
            )}
          </>
        )}
      </div>
      <div className="tools" onClick={(e) => e.stopPropagation()}>
        <button className="icon-btn" title={canPlay ? T.playFrom : T.audioUnavailable} aria-label={`${T.playFrom} ${formatTimestamp(seg.start_seconds)}`} disabled={!canPlay} onClick={() => onSeek(seg.start_seconds)} type="button">
          <IconPlay />
        </button>
        {canEdit && !editing && (
          <button className="icon-btn" title={T.editText} aria-label={`${T.editText} ${formatTimestamp(seg.start_seconds)}`} onClick={() => { setDraft(text); setEditing(true); }} type="button" data-testid="edit-segment">
            <IconEdit />
          </button>
        )}
      </div>
    </div>
  );
}

function SpeakerTurnRow({ turn, speakers, activeId, query, canEdit, canPlay, onSeek, onSaved }: {
  turn: TranscriptTurn;
  speakers: Speaker[];
  activeId: string | null;
  query: string;
  canEdit: boolean;
  canPlay: boolean;
  onSeek: (seconds: number) => void;
  onSaved: (segment: Segment) => void;
}) {
  const name = speakerName(turn.speaker_label, speakers);
  return (
    <section className="speaker-turn" aria-labelledby={`turn-speaker-${turn.id}`} data-testid="speaker-turn" data-speaker={turn.speaker_label}>
      <div className="speaker-turn-heading">
        <h4 className="speaker" id={`turn-speaker-${turn.id}`}>
          <span className="sw" style={{ background: speakerColor(turn.speaker_label) }} />
          {name}
        </h4>
      </div>
      <div className="speaker-turn-parts">
        {turn.segments.map(seg => <SegmentRow key={seg.id} seg={seg}
          active={seg.id === activeId} query={query} canEdit={canEdit} canPlay={canPlay} onSeek={onSeek} onSaved={onSaved} />)}
      </div>
    </section>
  );
}

export function TranscriptViewer({ transcript, onChange }: { transcript: Transcript; onChange: (tr: Transcript) => void }) {
  const { can } = useAuth();
  const [query, setQuery] = useState("");
  const [speakerFilter, setSpeakerFilter] = useState("");
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioError, setAudioError] = useState(false);
  const [audioAttempt, setAudioAttempt] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const editedCount = transcript.segments.filter(segment => segment.edited_text !== null).length;
  const pendingSuggestions = transcript.speakers.filter(s => s.identification_status === "SUGGESTED" && s.suggested_name && !s.identity_id).length;
  const speakerOptions = useMemo(() => transcriptSpeakerOptions(transcript.speakers, transcript.segments), [transcript.speakers, transcript.segments]);
  useEffect(() => { if (!speakerOptions.some(o => o.key === speakerFilter)) setSpeakerFilter(""); }, [speakerOptions, speakerFilter]);

  useEffect(() => {
    let url: string | null = null;
    let cancelled = false;
    setAudioUrl(null);
    setAudioError(false);
    setCurrentTime(0);
    if (transcript.audio_available) {
      fetchBlobUrl(`/recordings/${transcript.recording_id}/audio`)
        .then((u) => {
          if (cancelled) { URL.revokeObjectURL(u); return; }
          url = u;
          setAudioUrl(u);
        })
        .catch(() => { if (!cancelled) setAudioError(true); });
    }
    return () => {
      cancelled = true;
      if (url) URL.revokeObjectURL(url);
    };
  }, [transcript.recording_id, transcript.audio_available, audioAttempt]);

  // Group before filtering so hiding another speaker never joins separate turns.
  const turns = useMemo(() => groupTranscriptTurns(transcript.segments), [transcript.segments]);
  const visible = useMemo(
    () =>
      turns.filter(
        (turn) => (!speakerFilter || speakerOptions.find(o => o.key === speakerFilter)?.labels.includes(turn.speaker_label)) && (!query || turn.text.includes(query)),
      ),
    [turns, speakerFilter, speakerOptions, query],
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
    <section className="transcript-workspace" data-testid="transcript-workspace">
      <header className="workspace-heading"><div><span className="workspace-eyebrow">مراجعة النص المفرغ</span><h2>راجع الحوار، مقطعاً بمقطع</h2><p>استمع إلى التسجيل، وابحث في الحديث، وصحّح النص عند الحاجة.</p></div>
        <Link className="btn" to={`/investigations/${transcript.session_id}?tab=speakers`}><IconUsers />مراجعة المتحدثين<IconChevronLeft /></Link>
      </header>
      <div className="transcript-summary" aria-label="ملخص النص"><span><IconFile /><strong>{transcript.segments.length}</strong> مقاطع نصية</span><span><IconUsers /><strong>{speakerOptions.length}</strong> متحدثون في النص</span><span><IconEdit /><strong>{editedCount}</strong> مقاطع معدّلة</span><span className="transcript-summary-hint">التعديلات تحفظ النص الأصلي للمقارنة</span></div>
    <div className="transcript-layout">
      <div className="card" data-testid="transcript">
        {can("voice.identify") && pendingSuggestions > 0 && <div className="card-body" data-testid="transcript-voice-suggestions">
          <Alert kind="info">
            <p>{T.voicePendingSuggestions.replace("{n}", String(pendingSuggestions))}</p>
            <Link to={`/investigations/${transcript.session_id}?tab=speakers`} className="btn btn-sm">{T.voiceReviewSuggestions}</Link>
          </Alert>
        </div>}
        <div className="transcript-review-controls">
        <div className="transcript-toolbar">
          <div className="transcript-search">
            <IconSearch /><input className="input" type="search" placeholder={T.searchTranscript} value={query} onChange={(e) => setQuery(e.target.value)} aria-label={T.searchTranscript} />
          </div>
          <select className="select" value={speakerFilter} onChange={(e) => setSpeakerFilter(e.target.value)} aria-label={T.speakerFilter}>
            <option value="">{T.allSpeakers}</option>
            {speakerOptions.map((s) => (
              <option key={s.key} value={s.key}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <div className="player">
          <div className="transcript-player-label"><IconWave /><span>التسجيل الصوتي</span></div>
          {audioUrl ? (
            <audio ref={audioRef} src={audioUrl} controls preload="metadata" aria-label="تشغيل تسجيل الجلسة" onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)} data-testid="audio-player" />
          ) : audioError || !transcript.audio_available ? (
            <div className="transcript-audio-notice"><span>{T.audioUnavailable}</span>{audioError && <button className="btn btn-sm" onClick={() => setAudioAttempt(value => value + 1)} type="button">إعادة تحميل الصوت</button>}</div>
          ) : (
            <span className="muted small">{T.loading}</span>
          )}
          <div className="ptime num">
            <span>{formatClock(currentTime)}</span>
          </div>
        </div>
        </div>
        <div className="transcript-result-count" role="status"><span>عرض {visible.reduce((count, turn) => count + turn.segments.length, 0)} من {transcript.segments.length} مقاطع</span>
          {(query || speakerFilter) ? <button type="button" className="btn btn-ghost btn-sm" onClick={() => { setQuery(""); setSpeakerFilter(""); }}>مسح التصفية</button> : <span>{can("transcripts.edit") ? "استخدم رمز القلم لتعديل أي مقطع" : "عرض النص فقط"}</span>}</div>
        <div className="segments">
          {visible.length === 0 && <div className="workspace-empty"><IconSearch /><h3>{transcript.segments.length ? "لا توجد مقاطع مطابقة" : "لا توجد مقاطع نصية"}</h3><p>{transcript.segments.length ? "جرّب كلمة أخرى أو أزل تصفية المتحدث لعرض الحوار كاملاً." : "راجع نتيجة معالجة التسجيل من تبويب التسجيل."}</p></div>}
          {visible.map((turn) => (
            <SpeakerTurnRow key={turn.id} turn={turn} speakers={transcript.speakers} activeId={activeId} query={query} canEdit={can("transcripts.edit")} canPlay={!!audioUrl} onSeek={seek} onSaved={onSaved} />
          ))}
        </div>
      </div>

      <aside className="transcript-review-aside">
        <section className="card transcript-speaker-nav"><div className="card-header"><div><h3>المتحدثون في النص</h3><p className="workspace-section-hint">اختر اسماً لعرض مقاطعه فقط.</p></div></div>
          <div className="transcript-speaker-buttons"><button type="button" aria-pressed={!speakerFilter} onClick={() => setSpeakerFilter("")}><IconUsers /><span>الحوار كاملاً</span><b>{transcript.segments.length}</b></button>
            {speakerOptions.map(option => <button type="button" key={option.key} aria-pressed={speakerFilter === option.key} onClick={() => setSpeakerFilter(option.key)}><span className="transcript-speaker-dot" style={{ background: speakerColor(option.labels[0]) }} /><span>{option.name}</span><b>{transcript.segments.filter(segment => option.labels.includes(segment.speaker_label)).length}</b></button>)}
          </div>
          <div className="transcript-aside-footnote"><Link to={`/investigations/${transcript.session_id}?tab=speakers`}>تحديد الهويات وتعديل الصفات<IconChevronLeft /></Link></div>
        </section>
        {transcript.warnings.length > 0 && <Alert kind="warning"><strong>{T.warnings}</strong><ul>{transcript.warnings.map((warning, index) => <li key={index}>{warning}</li>)}</ul></Alert>}
        <details className="card transcript-model-details"><summary>تفاصيل المصدر والمعالجة</summary>
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
          </div>
        </details>
      </aside>
    </div>
    </section>
  );
}
