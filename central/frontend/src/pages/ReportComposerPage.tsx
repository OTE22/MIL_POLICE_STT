import { useCallback, useEffect, useState } from "react";
import { useBlocker, useParams } from "react-router-dom";
import { http, ApiError } from "@/api/client";
import type { Investigation, ReportDraft } from "@/api/types";
import { useAuth } from "@/lib/auth";
import { HtmlReportEditor } from "@/components/HtmlReportEditor";
import { Alert, Loading } from "@/components/ui";
import { IntakeReadiness } from "@/components/IntakeReadiness";

export function ReportComposerPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const [session, setSession] = useState<Investigation | null>(null);
  const [draft, setDraft] = useState<ReportDraft | null>(null);
  const [error, setError] = useState("");
  const [dirty, setDirty] = useState(false);
  const markDirty = useCallback((_id: string, value: boolean) => setDirty(value), []);
  const blocker = useBlocker(dirty);
  useEffect(() => {
    if (blocker.state !== "blocked") return;
    if (window.confirm("لديك تعديلات غير محفوظة. هل تريد مغادرة المحضر دون حفظها؟")) blocker.proceed();
    else blocker.reset();
  }, [blocker]);
  const load = useCallback(async () => {
    try {
      const investigation = await http.get<Investigation>(`/investigations/${id}`);
      setSession(investigation);
      try { await http.get(`/investigations/${id}/report/html`); }
      catch (error) {
        if (!(error instanceof ApiError) || error.status !== 404 || !can("reports.generate")) throw error;
        if (investigation.intake_readiness?.ready === false) return;
        await http.post(`/investigations/${id}/report/html`, {});
      }
      setDraft(await http.get<ReportDraft>(`/investigations/${id}/report`));
      setSession(investigation);
    } catch { setError("\u062a\u0639\u0630\u0631 \u062a\u062d\u0645\u064a\u0644 \u0627\u0644\u0645\u062d\u0636\u0631. \u0623\u0639\u062f \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629."); }
  }, [id, can]);
  useEffect(() => { void load(); }, [load]);
  if (error) return <Alert kind="danger">{error}</Alert>;
  if (session && !draft && session.intake_readiness?.ready === false) return <IntakeReadiness session={session} />;
  if (!session || !draft) return <Loading />;
  return <HtmlReportEditor key={`${session.id}-${draft.status}`} session={session} draft={draft}
    editable={can("reports.generate") && draft.status !== "FINAL" && !["CLOSED", "ARCHIVED"].includes(session.workflow_state)}
    onStatusChange={() => void load()} onDirtyChange={markDirty} />;
}
