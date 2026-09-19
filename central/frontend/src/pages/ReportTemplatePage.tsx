/* القالب الرسمي للمحضر — intentionally small.
 *
 * The organisation has ONE official format, so this is not a document designer: no
 * drag-and-drop, no field positioning, no fonts or margins. It is "download the current
 * form, edit it in Word, upload the replacement, activate it" — plus the history of which
 * version printed which reports.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, downloadFile, http } from "@/api/client";
import type { ReportTemplateList, ReportTemplateVersion } from "@/api/types";
import { formatDateTime } from "@/lib/format";
import { T, errorMessage } from "@/lib/i18n";
import { Alert, Badge, Loading, useToast } from "@/components/ui";

function StatusBadge({ v }: { v: ReportTemplateVersion }) {
  if (v.validation_status === "VALID") return <Badge kind="green">{T.templateValid}</Badge>;
  if (v.validation_status === "INVALID") return <Badge kind="red">{T.templateInvalid}</Badge>;
  return <Badge kind="gray">{T.templateUnvalidated}</Badge>;
}

export function ReportTemplatePage() {
  const toast = useToast();
  const [data, setData] = useState<ReportTemplateList | null>(null);
  const [placeholders, setPlaceholders] = useState<{ scalars: string[]; lists: string[]; required: string[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setData(await http.get<ReportTemplateList>("/report-templates"));
  }, []);

  useEffect(() => {
    void load().catch(() => setData(null));
    void http
      .get<{ scalars: string[]; lists: string[]; required: string[] }>("/report-templates/placeholders")
      .then(setPlaceholders)
      .catch(() => setPlaceholders(null));
  }, [load]);

  const run = async (fn: () => Promise<unknown>, success?: string) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
      if (success) toast.success(success);
    } catch (err) {
      const message = err instanceof ApiError ? errorMessage(err.code) : T.err_generic;
      setError(message);
      toast.error(message);
    } finally {
      setBusy(false);
    }
  };

  if (!data) return <Loading />;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{T.templateTitle}</h1>
          <p className="muted">{T.templateIntro}</p>
        </div>
        <div className="actions">
          <input
            ref={fileInput}
            type="file"
            accept=".docx"
            style={{ display: "none" }}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = "";
              if (file) void run(() => http.upload("/report-templates", file), T.templateUploaded);
            }}
            data-testid="template-file"
          />
          <button
            className="btn btn-primary"
            type="button"
            disabled={busy}
            onClick={() => fileInput.current?.click()}
            data-testid="template-upload"
          >
            {T.templateUpload}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-16">
          <Alert kind="danger">{error}</Alert>
        </div>
      )}

      {!data.production_ready && (
        <div className="mb-16">
          <Alert kind="warning">
            <div data-testid="template-not-official">⚠ {T.templateNotOfficial}</div>
            <div className="muted small mt-8">{T.templateNotOfficialHint}</div>
          </Alert>
        </div>
      )}

      <div className="card">
        <div className="card-head">{T.templateCurrent}</div>
        <div className="card-body">
          {!data.active ? (
            <div className="muted center">{T.templateNone}</div>
          ) : (
            <div className="person-card" data-testid="template-active">
              <div className="person-head">
                <div className="flex gap wrap">
                  <strong>
                    {T.templateVersion} <span className="num">{data.active.version}</span>
                  </strong>
                  <span className="muted ltr small">{data.active.original_filename}</span>
                  <StatusBadge v={data.active} />
                  {data.active.is_development && <Badge kind="amber">{T.templateDevelopment}</Badge>}
                </div>
                <span className="muted small">
                  {data.active.activated_at ? formatDateTime(data.active.activated_at) : ""}
                </span>
              </div>
              <div className="muted small mono ltr" style={{ wordBreak: "break-all" }}>
                SHA-256 {data.active.sha256}
              </div>
              <div className="flex gap mt-8">
                <button
                  className="btn btn-sm"
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void run(() =>
                      downloadFile(
                        `/report-templates/${data.active!.id}/file`,
                        `report-template-v${data.active!.version}.docx`,
                      ),
                    )
                  }
                  data-testid="template-download"
                >
                  {T.templateDownload}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          {T.templateHistory} <span className="num muted">({data.versions.length})</span>
        </div>
        <div className="card-body">
          {data.versions.map((v) => (
            <div className="person-card" key={v.id} data-testid="template-version">
              <div className="person-head">
                <div className="flex gap wrap">
                  <strong className="num">{v.version}</strong>
                  <span className="muted ltr small">{v.original_filename}</span>
                  <StatusBadge v={v} />
                  {v.is_active && <Badge kind="blue">{T.templateActive}</Badge>}
                  {v.is_development && <Badge kind="amber">{T.templateDevelopment}</Badge>}
                  {v.reports_issued > 0 && (
                    <Badge kind="navy">
                      {T.templateReportsIssued.replace("{n}", String(v.reports_issued))}
                    </Badge>
                  )}
                </div>
                <span className="muted small">{formatDateTime(v.created_at)}</span>
              </div>
              {v.validation_status === "INVALID" && v.validation_message && (
                <div className="muted small ltr" style={{ wordBreak: "break-word" }}>
                  {v.validation_message}
                </div>
              )}
              <div className="flex gap wrap mt-8">
                {!v.is_active && v.validation_status === "VALID" && (
                  <button
                    className="btn btn-sm btn-primary"
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      void run(
                        () => http.post(`/report-templates/${v.id}/activate`, {}),
                        T.templateActivated,
                      )
                    }
                    data-testid="template-activate"
                  >
                    {T.templateActivate}
                  </button>
                )}
                <button
                  className="btn btn-sm"
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    void run(() =>
                      downloadFile(`/report-templates/${v.id}/file`, `report-template-v${v.version}.docx`),
                    )
                  }
                >
                  {T.templateDownload}
                </button>
                <button
                  className="btn btn-sm"
                  type="button"
                  disabled={busy}
                  onClick={() => void run(() => http.post(`/report-templates/${v.id}/revalidate`, {}))}
                >
                  {T.templateRevalidate}
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {placeholders && (
        <div className="card">
          <div className="card-head">{T.templatePlaceholders}</div>
          <div className="card-body">
            <div className="muted small mb-16">{T.templatePlaceholdersHint}</div>
            <div className="ltr mono small" style={{ lineHeight: 1.9 }}>
              {placeholders.scalars.map((p) => (
                <span key={p} style={{ display: "inline-block", marginInlineEnd: 12 }}>
                  {`{{ ${p} }}`}
                </span>
              ))}
            </div>
            <div className="muted small mt-16">{T.templateLoopHint}</div>
            <pre className="ltr mono small" style={{ whiteSpace: "pre-wrap" }}>
              {"{%tr for qa in qa_blocks %}\n  س: {{ qa.question }}\n  ج: {{ qa.answer }}\n{%tr endfor %}"}
            </pre>
          </div>
        </div>
      )}
    </>
  );
}
