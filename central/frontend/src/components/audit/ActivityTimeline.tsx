/* A readable activity timeline, shared by a session's سجل النشاط and the admin التدقيق page.
 *
 * Each row states what happened in one Arabic line. The identifiers that make an audit
 * record evidence - job ids, SHA-256, model revisions - stay one click away rather than
 * being dumped into the row. A recording's processing stages collapse into a single run,
 * because "this recording was processed" is one event to a person even though it is six
 * to the pipeline.
 */

import { useMemo, useState } from "react";

import { T } from "@/lib/i18n";
import { formatDateTime } from "@/lib/format";
import {
  type AuditCategory,
  type AuditDetail,
  type ProcessingRun,
  type TimelineEntry,
  CATEGORY_LABELS,
  auditCategory,
  auditDetails,
  auditHeadline,
  auditSummary,
  auditTone,
  groupTimeline,
  runDuration,
  runOutcomeLabel,
} from "@/lib/audit-format";

function DetailTable({ details }: { details: AuditDetail[] }) {
  return (
    <dl className="audit-details">
      {details.map((d) => (
        <div key={d.key}>
          <dt>{d.label}</dt>
          <dd className={/[A-Za-z0-9]/.test(d.value) && !/[؀-ۿ]/.test(d.value) ? "ltr" : undefined}>
            {d.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Disclosure({ label, count, children }: { label: string; count?: number; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="audit-more">
      <button type="button" className="audit-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="caret" aria-hidden>{open ? "▾" : "◂"}</span>
        {label}
        {count !== undefined && <span className="num"> ({count})</span>}
      </button>
      {open && children}
    </div>
  );
}

function EntryRow({ entry, withinSession }: { entry: TimelineEntry; withinSession: boolean }) {
  const summary = auditSummary(entry.action, entry.safe_metadata);
  const details = auditDetails(entry.action, entry.safe_metadata, { withinSession });
  const tone = auditTone(entry.action);
  return (
    <div className="tl-item" data-testid="activity-row" data-action={entry.action}>
      <div className="when num">{formatDateTime(entry.created_at)}</div>
      <div>
        <div className="what">
          <span className={`dot ${tone}`} aria-hidden />
          {auditHeadline(entry.action)}
        </div>
        {summary && <div className="audit-summary">{summary}</div>}
        <div className="meta">{entry.username ?? T.none}</div>
        {details.length > 0 && (
          <Disclosure label={T.auditTechnicalDetails}>
            <DetailTable details={details} />
          </Disclosure>
        )}
      </div>
    </div>
  );
}

function RunRow({ run, withinSession }: { run: ProcessingRun; withinSession: boolean }) {
  const duration = runDuration(run);
  const tone = run.outcome === "ok" ? "ok" : run.outcome === "failed" ? "danger" : run.outcome === "cancelled" ? "warn" : "info";
  return (
    <div className="tl-item" data-testid="activity-run" data-outcome={run.outcome}>
      <div className="when num">{formatDateTime(run.endedAt)}</div>
      <div>
        <div className="what">
          <span className={`dot ${tone}`} aria-hidden />
          {runOutcomeLabel(run.outcome)}
          {duration && <span className="muted small" style={{ marginInlineStart: 8 }}>{duration}</span>}
        </div>
        {run.summary && <div className="audit-summary">{run.summary}</div>}
        <div className="meta">{run.username ?? T.none}</div>
        <Disclosure label={T.auditStages} count={run.stages.length}>
          <div className="audit-stages">
            {run.stages.map((st) => {
              const d = auditDetails(st.action, st.safe_metadata, { withinSession });
              return (
                <div className="audit-stage" key={st.id}>
                  <span className="num when">{formatDateTime(st.created_at)}</span>
                  <span>
                    {auditHeadline(st.action)}
                    {d.length > 0 && (
                      <Disclosure label={T.auditTechnicalDetails}>
                        <DetailTable details={d} />
                      </Disclosure>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        </Disclosure>
      </div>
    </div>
  );
}

export function ActivityTimeline({
  entries,
  withinSession = false,
  showFilters = true,
}: {
  entries: TimelineEntry[];
  /** Inside one session, the session id on every record is noise - drop it. */
  withinSession?: boolean;
  showFilters?: boolean;
}) {
  const [category, setCategory] = useState<AuditCategory | "">("");

  // Which categories are actually present; offering empty filters is worse than none.
  const present = useMemo(() => {
    const set = new Set<AuditCategory>();
    entries.forEach((e) => set.add(auditCategory(e.action)));
    return [...set];
  }, [entries]);

  const filtered = useMemo(
    () => (category ? entries.filter((e) => auditCategory(e.action) === category) : entries),
    [entries, category],
  );
  const rows = useMemo(() => groupTimeline(filtered), [filtered]);

  return (
    <>
      {showFilters && present.length > 1 && (
        <div className="audit-filters" data-testid="activity-filters">
          <button
            type="button"
            className={`chip ${category === "" ? "active" : ""}`}
            onClick={() => setCategory("")}
          >
            {T.auditFilterAll}
          </button>
          {present.map((c) => (
            <button
              key={c}
              type="button"
              className={`chip ${category === c ? "active" : ""}`}
              onClick={() => setCategory(c)}
              data-category={c}
            >
              {CATEGORY_LABELS[c]}
            </button>
          ))}
        </div>
      )}
      <div className="timeline" data-testid="activity">
        {rows.length === 0 && <div className="muted center">{category ? T.auditNoMatch : T.noData}</div>}
        {rows.map((row) =>
          row.kind === "run" ? (
            <RunRow key={row.id} run={row} withinSession={withinSession} />
          ) : (
            <EntryRow key={row.id} entry={row.entry} withinSession={withinSession} />
          ),
        )}
      </div>
    </>
  );
}

/** The readable cell used by the admin التدقيق table, in place of a JSON dump. */
export function AuditCell({ entry }: { entry: TimelineEntry }) {
  const summary = auditSummary(entry.action, entry.safe_metadata);
  const details = auditDetails(entry.action, entry.safe_metadata);
  if (!summary && details.length === 0) return <span className="muted">—</span>;
  return (
    <div className="audit-cell">
      {summary && <div className="audit-summary">{summary}</div>}
      {details.length > 0 && (
        <Disclosure label={T.auditTechnicalDetails}>
          <DetailTable details={details} />
        </Disclosure>
      )}
    </div>
  );
}
