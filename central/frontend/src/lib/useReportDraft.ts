import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, http } from "@/api/client";
import { editableDocument, type HtmlReportDocument, type HtmlReportState } from "./html-report";

const fingerprint = (document: HtmlReportDocument) => JSON.stringify(editableDocument(document));

/** A single save queue. A response may advance the token, never overwrite newer typing. */
export function useReportDraft(path: string, editable: boolean) {
  const [saved, setSaved] = useState<HtmlReportState | null>(null);
  const [document, setDocument] = useState<HtmlReportDocument | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState<HtmlReportState | null>(null);
  const current = useRef<HtmlReportDocument | null>(null);
  const base = useRef<HtmlReportState | null>(null);
  const flight = useRef<Promise<HtmlReportState> | null>(null);
  const editVersion = useRef(0);
  const paused = useRef(false);
  const accept = useCallback((state: HtmlReportState) => {
    base.current = state; current.current = state.document;
    setSaved(state); setDocument(state.document); setError(""); setConflict(null); paused.current = false;
  }, []);
  const change = (fn: (value: HtmlReportDocument) => HtmlReportDocument) => {
    if (!current.current) return;
    editVersion.current += 1;
    current.current = fn(current.current);
    setDocument(current.current);
  };
  const flush = useCallback(async (): Promise<HtmlReportState> => {
    if (flight.current) { await flight.current; return flush(); }
    if (!base.current || !current.current) throw new Error("report_not_loaded");
    if (paused.current) throw new Error("report_save_paused");
    if (fingerprint(base.current.document) === fingerprint(current.current)) return base.current;
    const version = editVersion.current;
    const body = { expected_token: base.current.token, document: editableDocument(current.current) };
    setSaving(true);
    const request = http.put<HtmlReportState>(path, body).then(state => {
      base.current = state; setSaved(state); setError("");
      if (version === editVersion.current) { current.current = state.document; setDocument(state.document); }
      return state;
    }).catch(async (err: unknown) => {
      paused.current = true;
      if (err instanceof ApiError && err.code === "html_report_changed") {
        setError("تغيّر المحضر في نافذة أخرى. نصك محفوظ هنا؛ قارن النسختين قبل المصالحة.");
        try { setConflict(await http.get<HtmlReportState>(path)); } catch { /* retry remains available */ }
      } else setError("تعذر الحفظ. بقيت تعديلاتك في هذه الصفحة؛ تحقق من الاتصال والحقول ثم أعد المحاولة.");
      throw err;
    }).finally(() => { flight.current = null; setSaving(false); });
    flight.current = request;
    await request;
    return flush();
  }, [path]);
  const retry = async () => { paused.current = false; setError(""); return flush(); };
  const reconcile = (choices: Record<string, "local" | "server">, header: "local" | "server") => {
    if (!conflict || !current.current) return;
    const local = current.current;
    const ids = [...new Set([...local.blocks.map(b => b.id), ...conflict.document.blocks.map(b => b.id)])];
    const merged = { ...(header === "local" ? local : conflict.document), blocks: ids.flatMap(id => {
      const block = (choices[id] === "server" ? conflict.document : local).blocks.find(b => b.id === id);
      return block ? [block] : [];
    }) };
    base.current = conflict; setSaved(conflict); setConflict(null); paused.current = false; setError("");
    change(() => merged);
  };
  const dirty = !!document && !!saved && fingerprint(document) !== fingerprint(saved.document);
  useEffect(() => {
    if (!dirty || !editable || saving || error || saved?.status === "FINAL") return;
    const timer = window.setTimeout(() => { void flush().catch(() => undefined); }, 1000);
    return () => window.clearTimeout(timer);
  }, [document, dirty, editable, saving, error, saved?.status, flush]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  return { saved, document, saving, error, conflict, dirty, accept, change, flush, retry, reconcile };
}
