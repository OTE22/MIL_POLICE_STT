/* Versioned report layouts: annotate a PDF/image sample or upload a Word template.
 * Review and activation remain explicit; issued documents keep their original version. */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError, downloadFile, http } from "@/api/client";
import type { ReportTemplateList, ReportTemplateVersion } from "@/api/types";
import { formatDateTime } from "@/lib/format";
import { T, errorMessage } from "@/lib/i18n";
import { Alert, Badge, Loading, useToast } from "@/components/ui";
import { ReportLayoutDesigner } from "@/components/ReportLayoutDesigner";

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
  const [designing, setDesigning] = useState(false);
  const [editId, setEditId] = useState<string | undefined>();
  const [designerDirty, setDesignerDirty] = useState(false);
  const [deletedTemplateId, setDeletedTemplateId] = useState<string>();
  const openDesigner = (id?: string) => {
    if (designerDirty && !window.confirm("لديك تغييرات غير محفوظة. هل تريد مغادرة التصميم الحالي؟")) return;
    setDesignerDirty(false); setEditId(id); setDesigning(true);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setData(await http.get<ReportTemplateList>("/report-templates"));
  }, []);

  useEffect(() => {
    void load().catch(err => setError(err instanceof ApiError ? errorMessage(err.code) : T.err_generic));
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

  const deleteTemplate = (version: ReportTemplateVersion) => {
    const editing = designing && editId === version.id;
    const warning = editing && designerDirty ? "\nستُفقد أيضاً التغييرات غير المحفوظة في المصمم." : "";
    if (!window.confirm(`حذف نسخة القالب ${version.version} (${version.original_filename || 'قالب المحضر'}) نهائياً؟ لا يمكن التراجع عن هذا الإجراء.${warning}`)) return;
    void run(async () => {
      const next = await http.del<ReportTemplateList>(`/report-templates/${version.id}`);
      setData(next);
      setDeletedTemplateId(version.id);
      if (editing) { setDesigning(false); setEditId(undefined); setDesignerDirty(false); }
    }, "تم حذف نسخة القالب");
  };

  if (!data) return error ? <Alert kind="danger">{error}<button className="btn" onClick={() => void load().catch(() => setError(T.err_generic))}>إعادة المحاولة</button></Alert> : <Loading />;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{T.templateTitle}</h1>
          <p className="muted">{T.templateIntro}</p>
        </div>
        <div className="actions">
          <button className="btn btn-primary" disabled={designing && !editId} onClick={() => openDesigner()}>＋ تصميم قالب من نموذج</button>
          {designing && <button className="btn" onClick={() => {
            if (designerDirty && !window.confirm("لديك تغييرات غير محفوظة. هل تريد إغلاق المصمم؟")) return;
            setDesigning(false); setDesignerDirty(false);
          }}>إغلاق المصمم</button>}
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
            className="btn"
            type="button"
            disabled={busy}
            onClick={() => fileInput.current?.click()}
            data-testid="template-upload"
          >
            {T.templateUpload}
          </button>
        </div>
      </div>

      {designing && <ReportLayoutDesigner key={editId ?? 'new'} editId={editId} deletedTemplateId={deletedTemplateId} onDirtyChange={setDesignerDirty} onSaved={() => void load().catch(() => setError(T.err_generic))} />}

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
              <details className="muted small"><summary>تفاصيل التحقق من الملف</summary><div className="mono ltr" style={{ wordBreak: "break-all" }}>SHA-256 {data.active.sha256}</div></details>
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
            <details className="person-card template-version-row" key={v.id} open={v.id === data.versions[0]?.id} data-testid="template-version">
              <summary className="person-head">
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
              </summary>
              {v.validation_status === "INVALID" && v.validation_message && (
                <div className="muted small ltr" style={{ wordBreak: "break-word" }}>
                  {v.validation_message}
                </div>
              )}
              <div className="flex gap wrap mt-8">
                <button className="btn btn-sm btn-danger" disabled={busy || v.is_active || v.reports_issued > 0}
                  onClick={() => deleteTemplate(v)} data-testid="template-delete">حذف القالب</button>
                <button className="btn btn-sm" onClick={() => openDesigner(v.id)}>تعديل مربعات الحقول</button>
                {v.validation_status === "VALID" && <button className="btn btn-sm" onClick={() => void run(() => downloadFile(`/report-templates/${v.id}/preview`, 'template-preview.docx'))}>معاينة Word</button>}
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
              {(v.is_active || v.reports_issued > 0) && <p className="muted small mt-8">
                {v.reports_issued > 0 ? "لا يمكن حذف هذه النسخة لأنها مرتبطة بمحاضر صادرة." : "لحذف هذه النسخة، فعّل نسخة أخرى أولاً."}
              </p>}
            </details>
          ))}
        </div>
      </div>

      {placeholders && (
        <details className="card template-advanced">
          <summary>إعداد قوالب Word المتقدمة · {T.templatePlaceholders}</summary>
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
        </details>
      )}
    </>
  );
}
