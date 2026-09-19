/* محضر تحقيق — the content composer.
 *
 * The investigator controls WHAT the report says: which recordings, which text, the header
 * fields, the wording of every س/ج. They deliberately cannot control how it LOOKS - no font,
 * size, colour, margin or signature-position controls exist here, because the official Word
 * template owns the layout. That separation is the whole design.
 *
 * Nothing on this page writes to the transcript. Editing a block changes the report's copy;
 * the source text stays beside it, one click away, so an edit always reads as an edit.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ApiError, downloadFile, http } from "@/api/client";
import type {
  GeneratedReport,
  Investigation,
  ReportArchive,
  ReportDraft,
  ReportQABlock,
  ReportVerification,
} from "@/api/types";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatDuration } from "@/lib/format";
import { T, errorMessage } from "@/lib/i18n";
import { Alert, Badge, Field, Loading, useToast } from "@/components/ui";

function seconds(value: number | null): string {
  if (value == null) return "";
  const total = Math.floor(value);
  const mm = String(Math.floor(total / 60)).padStart(2, "0");
  const ss = String(total % 60).padStart(2, "0");
  return `${mm}:${ss}`;
}

/** One س/ج exchange: printed text on the left of the operator's attention, evidence behind it. */
const FUSHA_BADGE: Record<string, { label: () => string; kind: "gray" | "blue" | "green" | "amber" }> = {
  AI_SUGGESTED: { label: () => T.reportFushaSuggested, kind: "amber" },
  APPROVED: { label: () => T.reportFushaApproved, kind: "green" },
  HUMAN_EDITED: { label: () => T.reportFushaEdited, kind: "blue" },
  REJECTED: { label: () => T.reportFushaRejected, kind: "gray" },
};

function QABlockCard({
  block,
  index,
  canMergeNext,
  busy,
  fushaAvailable,
  onEdit,
  onExclude,
  onRestore,
  onMerge,
  onSplit,
  onFusha,
  onFushaDecide,
  sessionId,
}: {
  block: ReportQABlock;
  index: number;
  canMergeNext: boolean;
  busy: boolean;
  fushaAvailable: boolean;
  onEdit: (question: string, answer: string) => void;
  onExclude: (reason: string) => void;
  onRestore: () => void;
  onMerge: () => void;
  onSplit: (head: string, tail: string) => void;
  onFusha: () => void;
  onFushaDecide: (accept: boolean, edited?: { question?: string; answer?: string }) => void;
  sessionId: string;
}) {
  const [question, setQuestion] = useState(block.report_question_text ?? "");
  const [answer, setAnswer] = useState(block.report_answer_text ?? "");
  const [showSource, setShowSource] = useState(false);
  const [splitAt, setSplitAt] = useState<number | null>(null);

  // The server is the source of truth; adopt its text whenever it changes underneath.
  useEffect(() => setQuestion(block.report_question_text ?? ""), [block.report_question_text]);
  useEffect(() => setAnswer(block.report_answer_text ?? ""), [block.report_answer_text]);

  const dirty =
    question !== (block.report_question_text ?? "") || answer !== (block.report_answer_text ?? "");
  const changedFromSource =
    (block.report_question_text ?? "") !== (block.question_source_text ?? "") ||
    (block.report_answer_text ?? "") !== (block.answer_source_text ?? "");

  return (
    <div
      className="person-card"
      data-testid="qa-block"
      data-sequence={block.sequence}
      style={block.included_in_report ? undefined : { opacity: 0.6 }}
    >
      <div className="person-head">
        <div className="flex gap wrap">
          <strong className="num">{index}</strong>
          {block.answer_speaker_name && (
            <span className="muted small">{block.answer_speaker_name}</span>
          )}
          {!block.answer_speaker_resolved && block.answer_speaker_id && (
            <Badge kind="amber">{T.reportUnresolvedTitle}</Badge>
          )}
          {changedFromSource && <Badge kind="blue">{T.reportEdited}</Badge>}
          {block.fusha_status !== "NOT_REQUESTED" && FUSHA_BADGE[block.fusha_status] && (
            <Badge kind={FUSHA_BADGE[block.fusha_status].kind}>
              {FUSHA_BADGE[block.fusha_status].label()}
            </Badge>
          )}
          {!block.included_in_report && <Badge kind="gray">{T.reportExcluded}</Badge>}
        </div>
        <span className="muted small num" dir="ltr">
          {seconds(block.start_seconds)} — {seconds(block.end_seconds)}
        </span>
      </div>

      <Field label={T.reportQuestion}>
        <textarea
          className="input"
          rows={2}
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={busy || !block.included_in_report}
          data-testid="qa-question"
        />
      </Field>
      <Field label={T.reportAnswer}>
        <textarea
          className="input"
          rows={3}
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onSelect={(e) => setSplitAt((e.target as HTMLTextAreaElement).selectionStart)}
          disabled={busy || !block.included_in_report}
          data-testid="qa-answer"
        />
      </Field>

      {showSource && (
        <div className="audit-stages" data-testid="qa-source">
          <div className="audit-stage">
            <span className="muted small">{T.reportSourceText}</span>
            <span>
              {T.reportQuestion}: {block.question_source_text || "—"}
              <br />
              {T.reportAnswer}: {block.answer_source_text || "—"}
            </span>
          </div>
        </div>
      )}

      {/* الصياغة بالفصحى: source, current wording, suggestion — then a human decides. */}
      {block.fusha_status === "AI_SUGGESTED" &&
        (block.llm_suggested_question || block.llm_suggested_answer) && (
          <div className="audit-stages" data-testid="fusha-review">
            <div className="audit-stage">
              <span className="muted small">{T.reportFushaSuggestion}</span>
              <span>
                {block.llm_suggested_question && (
                  <>
                    {T.reportQuestion}: {block.llm_suggested_question}
                    <br />
                  </>
                )}
                {block.llm_suggested_answer && (
                  <>
                    {T.reportAnswer}: {block.llm_suggested_answer}
                  </>
                )}
              </span>
            </div>
            <div className="flex gap wrap mt-8">
              <button
                className="btn btn-sm btn-primary"
                type="button"
                disabled={busy}
                onClick={() => onFushaDecide(true)}
                data-testid="fusha-approve"
              >
                {T.reportFushaApprove}
              </button>
              <button
                className="btn btn-sm"
                type="button"
                disabled={busy}
                onClick={() =>
                  onFushaDecide(true, {
                    question: block.llm_suggested_question ?? undefined,
                    answer: answer || undefined,
                  })
                }
              >
                {T.reportFushaEdit}
              </button>
              <button
                className="btn btn-sm btn-danger"
                type="button"
                disabled={busy}
                onClick={() => onFushaDecide(false)}
                data-testid="fusha-reject"
              >
                {T.reportFushaReject}
              </button>
            </div>
            <div className="muted small mt-8">{T.reportFushaHumanNote}</div>
          </div>
        )}

      <div className="flex gap wrap mt-8">
        {dirty && (
          <button
            className="btn btn-sm btn-primary"
            type="button"
            disabled={busy}
            onClick={() => onEdit(question, answer)}
            data-testid="qa-save"
          >
            {T.save}
          </button>
        )}
        <button className="btn btn-sm" type="button" onClick={() => setShowSource((v) => !v)}>
          {showSource ? T.reportHideSource : T.reportShowSource}
        </button>
        {block.source_recording_ids.length > 0 && (
          <Link className="btn btn-sm" to={`/investigations/${sessionId}?tab=transcript`}>
            {T.reportViewInTranscript}
          </Link>
        )}
        {block.included_in_report ? (
          <>
            {fushaAvailable && (
              <button
                className="btn btn-sm"
                type="button"
                disabled={busy}
                onClick={onFusha}
                data-testid="fusha-request"
              >
                {T.reportFushaRequest}
              </button>
            )}
            {canMergeNext && (
              <button className="btn btn-sm" type="button" disabled={busy} onClick={onMerge}>
                {T.reportMerge}
              </button>
            )}
            <button
              className="btn btn-sm"
              type="button"
              disabled={busy || splitAt == null || splitAt <= 0 || splitAt >= answer.length}
              title={T.reportSplitHint}
              onClick={() => onSplit(answer.slice(0, splitAt ?? 0).trim(), answer.slice(splitAt ?? 0).trim())}
              data-testid="qa-split"
            >
              {T.reportSplit}
            </button>
            <button
              className="btn btn-sm btn-danger"
              type="button"
              disabled={busy}
              onClick={() => onExclude(window.prompt(T.reportExcludeReason) ?? "")}
              data-testid="qa-exclude"
            >
              {T.reportExclude}
            </button>
          </>
        ) : (
          <button className="btn btn-sm" type="button" disabled={busy} onClick={onRestore} data-testid="qa-restore">
            {T.reportRestore}
          </button>
        )}
      </div>
      {!block.included_in_report && block.exclusion_reason && (
        <div className="muted small mt-8">{block.exclusion_reason}</div>
      )}
    </div>
  );
}

export function ReportComposerPage() {
  const { id } = useParams<{ id: string }>();
  const sessionId = id as string;
  const navigate = useNavigate();
  const toast = useToast();
  const { can } = useAuth();
  const [session, setSession] = useState<Investigation | null>(null);
  const [draft, setDraft] = useState<ReportDraft | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState({
    report_number: "",
    case_subject: "",
    report_date: "",
    report_time: "",
    location: "",
    intro_text: "",
    closing_text: "",
  });
  const [showPreview, setShowPreview] = useState(false);
  const [archive, setArchive] = useState<ReportArchive | null>(null);
  const [verified, setVerified] = useState<Record<string, ReportVerification>>({});
  const mayEdit = can("reports.generate");
  const mayFinalize = can("reports.finalize");

  const loadArchive = useCallback(async () => {
    setArchive(await http.get<ReportArchive>(`/investigations/${sessionId}/reports`));
  }, [sessionId]);

  const adopt = useCallback((body: ReportDraft) => {
    setDraft(body);
    setMeta({
      report_number: body.report_number ?? "",
      case_subject: body.case_subject ?? "",
      report_date: body.report_date ?? "",
      report_time: (body.report_time ?? "").slice(0, 5),
      location: body.location ?? "",
      intro_text: body.intro_text ?? "",
      closing_text: body.closing_text ?? "",
    });
  }, []);

  const fail = useCallback(
    (err: unknown) => toast.error(err instanceof ApiError ? errorMessage(err.code) : T.err_generic),
    [toast],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const info = await http.get<Investigation>(`/investigations/${sessionId}`);
        if (!cancelled) setSession(info);
        try {
          const existing = await http.get<ReportDraft>(`/investigations/${sessionId}/report`);
          if (!cancelled) adopt(existing);
        } catch (err) {
          // No draft yet: build one on first open, which is the zero-config path.
          if (err instanceof ApiError && err.status === 404 && mayEdit) {
            const created = await http.post<ReportDraft>(`/investigations/${sessionId}/report`, {});
            if (!cancelled) adopt(created);
          } else if (!cancelled) {
            setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
          }
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic);
        if (!cancelled) await loadArchive().catch(() => setArchive(null));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, adopt, mayEdit, loadArchive]);

  const call = useCallback(
    async (fn: () => Promise<ReportDraft>, success?: string) => {
      setBusy(true);
      try {
        adopt(await fn());
        if (success) toast.success(success);
      } catch (err) {
        fail(err);
      } finally {
        setBusy(false);
      }
    },
    [adopt, fail, toast],
  );

  const saveMeta = () =>
    call(
      () =>
        http.put<ReportDraft>(`/investigations/${sessionId}/report`, {
          report_number: meta.report_number,
          case_subject: meta.case_subject,
          report_date: meta.report_date || null,
          report_time: meta.report_time || null,
          location: meta.location,
          intro_text: meta.intro_text,
          closing_text: meta.closing_text,
        }),
      T.reportSaved,
    );

  const included = useMemo(
    () => (draft?.qa_blocks ?? []).filter((b) => b.included_in_report),
    [draft],
  );

  if (loading) return <Loading />;
  if (error && !draft)
    return (
      <div className="card">
        <div className="card-body">
          <Alert kind="danger">{error}</Alert>
          <button className="btn mt-8" type="button" onClick={() => navigate(`/investigations/${sessionId}`)}>
            {T.back}
          </button>
        </div>
      </div>
    );
  if (!draft) return null;

  const blockPath = (blockId: string) => `/investigations/${sessionId}/report/blocks/${blockId}`;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{T.reportTitle}</h1>
          <p>
            <Link to={`/investigations/${sessionId}`}>{session?.title ?? sessionId}</Link>{" "}
            <span className="muted mono">{session?.session_number}</span>{" "}
            {draft.report_version_count > 0 && (
              <Badge kind="navy">
                {T.reportVersionsExist.replace("{n}", String(draft.report_version_count))}
              </Badge>
            )}
          </p>
        </div>
        <div className="actions">
          <button
            className="btn"
            type="button"
            onClick={() => setShowPreview((v) => !v)}
            data-testid="report-preview-toggle"
          >
            {T.reportPreview}
          </button>
          {mayEdit && (
            <button
              className="btn btn-primary"
              type="button"
              disabled={busy}
              onClick={() => void saveMeta()}
              data-testid="report-save"
            >
              {busy ? T.reportSaving : T.reportSave}
            </button>
          )}
        </div>
      </div>

      <div className="muted small mb-16">{T.reportEvidenceNote}</div>

      {draft.stale.length > 0 && (
        <div className="mb-16">
          <Alert kind="warning">
            <div data-testid="report-stale">⚠ {T.reportStale}</div>
            {mayEdit && (
              <button
                className="btn btn-sm mt-8"
                type="button"
                disabled={busy}
                onClick={() => {
                  if (!window.confirm(T.reportRefreshConfirm)) return;
                  void call(
                    () => http.post<ReportDraft>(`/investigations/${sessionId}/report/refresh`, {}),
                    T.reportRefreshed,
                  );
                }}
                data-testid="report-refresh"
              >
                {T.reportRefresh}
              </button>
            )}
          </Alert>
        </div>
      )}

      {draft.missing_fields.length > 0 && (
        <div className="mb-16">
          <Alert kind="warning">
            <div data-testid="report-missing">{T.reportMissingFields}</div>
            <ul>
              {draft.missing_fields.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          </Alert>
        </div>
      )}

      {/* ---- بيانات المحضر ------------------------------------------------ */}
      <div className="card">
        <div className="card-head">{T.reportSectionMeta}</div>
        <div className="card-body form-grid">
          <Field label={T.reportNumber} required>
            <input
              className="input"
              value={meta.report_number}
              onChange={(e) => setMeta({ ...meta, report_number: e.target.value })}
              disabled={!mayEdit}
              data-testid="report-number"
            />
          </Field>
          <Field label={T.reportSubject} required>
            <input
              className="input"
              value={meta.case_subject}
              onChange={(e) => setMeta({ ...meta, case_subject: e.target.value })}
              disabled={!mayEdit}
              data-testid="report-subject"
            />
          </Field>
          <Field label={T.reportLocation} required>
            <input
              className="input"
              value={meta.location}
              onChange={(e) => setMeta({ ...meta, location: e.target.value })}
              disabled={!mayEdit}
              data-testid="report-location"
            />
          </Field>
          <Field label={T.reportDate}>
            <input
              className="input"
              type="date"
              value={meta.report_date}
              onChange={(e) => setMeta({ ...meta, report_date: e.target.value })}
              disabled={!mayEdit}
            />
          </Field>
          <Field label={T.reportTime}>
            <input
              className="input"
              type="time"
              value={meta.report_time}
              onChange={(e) => setMeta({ ...meta, report_time: e.target.value })}
              disabled={!mayEdit}
            />
          </Field>
          <Field label={T.reportIntro} full>
            <textarea
              className="input"
              rows={2}
              value={meta.intro_text}
              onChange={(e) => setMeta({ ...meta, intro_text: e.target.value })}
              disabled={!mayEdit}
            />
          </Field>
          <Field label={T.reportClosing} full>
            <textarea
              className="input"
              rows={2}
              value={meta.closing_text}
              onChange={(e) => setMeta({ ...meta, closing_text: e.target.value })}
              disabled={!mayEdit}
            />
          </Field>
        </div>
      </div>

      {/* ---- التسجيلات + مصدر النص ---------------------------------------- */}
      <div className="card">
        <div className="card-head">{T.reportSectionRecordings}</div>
        <div className="card-body">
          {draft.recordings.map((rec) => (
            <label key={rec.id} className="checkbox" style={{ display: "block" }}>
              <input
                type="checkbox"
                checked={rec.selected}
                disabled={!mayEdit || busy || !rec.has_transcript}
                onChange={(e) => {
                  const next = draft.recordings
                    .filter((r) => (r.id === rec.id ? e.target.checked : r.selected))
                    .map((r) => r.id);
                  if (next.length === 0) {
                    toast.error(T.err_generic);
                    return;
                  }
                  void call(() =>
                    http.put<ReportDraft>(`/investigations/${sessionId}/report`, {
                      selected_recording_ids: next,
                    }),
                  );
                }}
                data-testid="report-recording"
              />
              <span className="num">{rec.index}.</span> {rec.original_filename}{" "}
              <span className="muted small">
                {rec.duration_seconds ? formatDuration(rec.duration_seconds) : ""}
                {!rec.has_transcript && ` — ${T.reportNoTranscripts}`}
              </span>
            </label>
          ))}

          <div className="mt-16">
            <Field label={T.reportSectionSource} hint={T.reportSourceHint}>
              <select
                className="input"
                value={draft.transcript_source_mode}
                disabled={!mayEdit || busy}
                onChange={(e) =>
                  void call(() =>
                    http.put<ReportDraft>(`/investigations/${sessionId}/report`, {
                      transcript_source_mode: e.target.value,
                    }),
                  )
                }
                data-testid="report-source-mode"
              >
                <option value="CORRECTED">{T.reportSourceCorrected}</option>
                <option value="ORIGINAL">{T.reportSourceOriginal}</option>
              </select>
            </Field>
          </div>
        </div>
      </div>

      {/* ---- التحقق من المتحدثين ------------------------------------------ */}
      <div className="card">
        <div className="card-head">{T.reportSectionSpeakers}</div>
        <div className="card-body">
          {draft.unresolved_speaker_labels.length === 0 ? (
            <div className="muted">{T.reportSpeakersResolved}</div>
          ) : (
            <Alert kind="warning">
              <div data-testid="report-unresolved">⚠ {T.reportUnresolvedTitle}</div>
              <div className="muted small mt-8">{T.reportUnresolvedHint}</div>
              <div className="mt-8">
                <Link className="btn btn-sm" to={`/investigations/${sessionId}?tab=speakers`}>
                  {T.identifySpeaker}
                </Link>
              </div>
              {mayEdit && (
                <label className="checkbox mt-8" style={{ display: "block" }}>
                  <input
                    type="checkbox"
                    checked={draft.unresolved_ack}
                    disabled={busy}
                    onChange={(e) =>
                      void call(() =>
                        http.put<ReportDraft>(`/investigations/${sessionId}/report`, {
                          unresolved_ack: e.target.checked,
                        }),
                      )
                    }
                    data-testid="report-unresolved-ack"
                  />
                  {T.reportUnresolvedAck}
                </label>
              )}
            </Alert>
          )}
          <div className="audit-stages mt-8">
            {draft.speakers.map((sp) => (
              <div className="audit-stage" key={sp.id}>
                <span className="num ltr">{sp.speaker_label}</span>
                <span className="flex gap wrap">
                  <span>{sp.report_name}</span>
                  {sp.legacy && <Badge kind="gray">{T.reportLegacySpeaker}</Badge>}
                  <Badge kind={sp.resolved ? "green" : "amber"}>
                    {sp.resolved ? T.reportSpeakersResolved : T.identifyUnknown}
                  </Badge>
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ---- الأسئلة والأجوبة --------------------------------------------- */}
      <div className="card">
        <div className="card-head">
          {T.reportSectionQA}{" "}
          <span className="num muted">
            ({included.length}/{draft.qa_blocks.length})
          </span>
        </div>
        <div className="card-body">
          {!draft.llm.available && (
            <div className="muted small mb-16" data-testid="fusha-unavailable">
              {T.reportFushaUnavailable}
            </div>
          )}
          {draft.qa_blocks.length === 0 ? (
            <div className="muted center">{T.none}</div>
          ) : (
            draft.qa_blocks.map((block, i) => (
              <QABlockCard
                key={block.id}
                block={block}
                index={i + 1}
                sessionId={sessionId}
                busy={busy || !mayEdit}
                canMergeNext={i + 1 < draft.qa_blocks.length}
                fushaAvailable={draft.llm.available && mayEdit}
                onFusha={() =>
                  void call(() => http.post<ReportDraft>(`${blockPath(block.id)}/fusha`, {}))
                }
                onFushaDecide={(accept, edited) =>
                  void call(() =>
                    http.post<ReportDraft>(`${blockPath(block.id)}/fusha/decision`, {
                      accept,
                      report_question_text: edited?.question ?? null,
                      report_answer_text: edited?.answer ?? null,
                    }),
                  )
                }
                onEdit={(question, answer) =>
                  void call(() =>
                    http.patch<ReportDraft>(blockPath(block.id), {
                      report_question_text: question,
                      report_answer_text: answer,
                    }),
                  )
                }
                onExclude={(reason) =>
                  void call(() => http.post<ReportDraft>(`${blockPath(block.id)}/exclude`, { reason }))
                }
                onRestore={() =>
                  void call(() => http.post<ReportDraft>(`${blockPath(block.id)}/restore`, {}))
                }
                onMerge={() =>
                  void call(() =>
                    http.post<ReportDraft>(`${blockPath(block.id)}/merge`, {
                      with_block_id: draft.qa_blocks[i + 1].id,
                    }),
                  )
                }
                onSplit={(head, tail) =>
                  void call(() =>
                    http.post<ReportDraft>(`${blockPath(block.id)}/split`, {
                      answer_head: head,
                      answer_tail: tail,
                    }),
                  )
                }
              />
            ))
          )}
        </div>
      </div>

      {/* ---- المحاضر الصادرة: immutable, hashed, verifiable ------------------ */}
      <div className="card" data-testid="report-archive">
        <div className="card-head">
          {T.reportArchive}{" "}
          <span className="num muted">({archive?.reports.length ?? 0})</span>
        </div>
        <div className="card-body">
          <div className="muted small mb-16">{T.reportFinalNote}</div>

          {archive && !archive.can_finalize && (
            <Alert kind="warning">
              <div data-testid="report-blocked">{T.reportBlocked}</div>
              <ul>
                {archive.blocked_reasons.map((r) => (
                  <li key={r}>{errorMessage(r)}</li>
                ))}
                {archive.missing_fields.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            </Alert>
          )}

          {mayEdit && draft.status === "FINAL" && (
            <button
              className="btn mt-8"
              type="button"
              disabled={busy}
              style={{ marginInlineEnd: 8 }}
              onClick={() => {
                if (!window.confirm(T.reportReopenConfirm)) return;
                void call(
                  () => http.post<ReportDraft>(`/investigations/${sessionId}/report/reopen`, {}),
                  T.reportReopened,
                );
              }}
              data-testid="report-reopen"
            >
              {T.reportReopen}
            </button>
          )}
          {mayFinalize && (
            <button
              className="btn btn-primary mt-8"
              type="button"
              disabled={busy || !archive?.can_finalize}
              onClick={() =>
                void (async () => {
                  setBusy(true);
                  try {
                    setArchive(
                      await http.post<ReportArchive>(`/investigations/${sessionId}/reports`, {}),
                    );
                    adopt(await http.get<ReportDraft>(`/investigations/${sessionId}/report`));
                    toast.success(T.reportIssued);
                  } catch (err) {
                    fail(err);
                    await loadArchive().catch(() => undefined);
                  } finally {
                    setBusy(false);
                  }
                })()
              }
              data-testid="report-finalize"
            >
              {busy ? T.reportIssuing : T.reportIssue}
            </button>
          )}

          {archive?.reports.length === 0 ? (
            <div className="muted center mt-16">{T.reportNoneIssued}</div>
          ) : (
            <div className="audit-stages mt-16">
              {archive?.reports.map((r: GeneratedReport) => (
                <div className="audit-stage" key={r.id} data-testid="issued-report">
                  <span className="num when">
                    {T.reportVersionLabel} {r.report_version}
                  </span>
                  <span className="flex gap wrap">
                    <span>{r.report_number || "—"}</span>
                    <span className="muted small">{formatDateTime(r.created_at)}</span>
                    <span className="muted small">
                      {T.reportIssuedBy}: {r.generated_by_name || "—"}
                    </span>
                    {r.template_is_development && <Badge kind="amber">{T.templateDevelopment}</Badge>}
                    {verified[r.id] && (
                      <Badge kind={verified[r.id].ok ? "green" : "red"}>
                        {verified[r.id].ok ? T.reportVerifyOk : T.reportVerifyBad}
                      </Badge>
                    )}
                    <button
                      className="btn btn-sm"
                      type="button"
                      onClick={() =>
                        void downloadFile(
                          `/investigations/${sessionId}/reports/${r.id}/file`,
                          `mahdar-v${r.report_version}.docx`,
                        ).catch(fail)
                      }
                      data-testid="report-download"
                    >
                      {T.reportDownload}
                    </button>
                    <button
                      className="btn btn-sm"
                      type="button"
                      onClick={() =>
                        void http
                          .get<ReportVerification>(
                            `/investigations/${sessionId}/reports/${r.id}/verify`,
                          )
                          .then((v) => setVerified((prev) => ({ ...prev, [r.id]: v })))
                          .catch(fail)
                      }
                      data-testid="report-verify"
                    >
                      {T.reportVerify}
                    </button>
                  </span>
                  <span className="muted small mono ltr" style={{ wordBreak: "break-all" }}>
                    {r.docx_sha256.slice(0, 32)}…
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ---- معاينة تقريبية: content only, never a Word renderer ---------- */}
      {showPreview && (
        <div className="card" data-testid="report-preview">
          <div className="card-head">{T.reportPreview}</div>
          <div className="card-body">
            <div className="muted small mb-16">{T.reportPreviewHint}</div>
            <h3>{meta.case_subject || T.reportSubject}</h3>
            <p className="muted small">
              {T.reportNumber}: <span className="num">{meta.report_number || "—"}</span> ·{" "}
              {T.reportLocation}: {meta.location || "—"} · {T.reportDate}:{" "}
              <span className="num">{meta.report_date || "—"}</span>
            </p>
            {meta.intro_text && <p>{meta.intro_text}</p>}
            {included.map((b, i) => (
              <p key={b.id}>
                <strong>
                  {T.reportQuestion} {i + 1}:
                </strong>{" "}
                {b.report_question_text}
                <br />
                <strong>{T.reportAnswer}:</strong> {b.report_answer_text}
              </p>
            ))}
            {meta.closing_text && <p>{meta.closing_text}</p>}
          </div>
        </div>
      )}
    </>
  );
}
