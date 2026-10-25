import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, http } from "@/api/client";
import type { Investigation, ReportDraft } from "@/api/types";
import { Alert, Field, Loading } from "@/components/ui";
import { blockLabel, editableDocument, importAnswers, newEntry, newNote, newStatement, renderHtmlReport,
  type HtmlReportDocument, type HtmlReportState, type ReportBlock, type StatementBlock, type StatementCatalogue } from "@/lib/html-report";

export function HtmlReportEditor({ session, draft, editable, onLegacy, onDirtyChange }: {
  session: Investigation; draft: ReportDraft; editable: boolean; onLegacy: () => void;
  onDirtyChange: (id: string, dirty: boolean) => void;
}) {
  const [saved, setSaved] = useState<HtmlReportState | null>(null);
  const [document, setDocument] = useState<HtmlReportDocument | null>(null);
  const [catalogue, setCatalogue] = useState<StatementCatalogue | null>(null);
  const [font, setFont] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [highlight, setHighlight] = useState(true);
  const [showSources, setShowSources] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [removed, setRemoved] = useState<{ block: ReportBlock; index: number } | null>(null);
  const frame = useRef<HTMLIFrameElement>(null);
  const path = `/investigations/${session.id}/report/html`;
  useEffect(() => {
    let cancelled = false;
    void Promise.all([http.get<HtmlReportState>(path), http.get<StatementCatalogue>("/report-forms/html-statement")])
      .then(([state, template]) => { if (!cancelled) { setSaved(state); setDocument(state.document); setCatalogue(template); setSelectedId(state.document.blocks[0]?.id ?? null); } })
      .catch(() => { if (!cancelled) setError("تعذر تحميل محضر HTML. أعد تحميل الصفحة."); });
    void fetch("/fonts/NotoNaskhArabic-Regular.ttf").then(response => { if (!response.ok) throw new Error("font"); return response.arrayBuffer(); })
      .then(buffer => {
        const reader = new FileReader();
        reader.onload = () => { if (!cancelled) setFont(String(reader.result)); };
        reader.readAsDataURL(new Blob([buffer], { type: "font/ttf" }));
      }).catch(() => { if (!cancelled) setError("تعذر تحميل الخط العربي للطباعة. أعد تحميل الصفحة لإكمال تنزيل الملف."); });
    return () => { cancelled = true; };
  }, [path]);
  const dirty = !!document && !!saved && JSON.stringify(editableDocument(document)) !== JSON.stringify(editableDocument(saved.document));
  useEffect(() => { onDirtyChange("html-report", dirty || busy); }, [dirty, busy, onDirtyChange]);
  useEffect(() => () => onDirtyChange("html-report", false), [onDirtyChange]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const preview = useMemo(() => document && catalogue ? renderHtmlReport(document, catalogue, session,
    { highlight, fontDataUrl: font, showSources }) : "", [document, catalogue, session, highlight, font, showSources]);
  const disabled = !editable || busy;
  const active = document?.blocks.find(block => block.id === selectedId);
  const activeFields = active?.type === "note" ? catalogue?.note.fields : catalogue?.fields;
  const change = (fn: (value: HtmlReportDocument) => HtmlReportDocument) => { setDocument(value => value ? fn(value) : value); setNotice(""); };
  const updateBlock = (id: string, fn: (block: ReportBlock) => ReportBlock) => change(value => ({ ...value, blocks: value.blocks.map(block => block.id === id ? fn(block) : block) }));
  const updateStatement = (id: string, fn: (block: StatementBlock) => StatementBlock) => updateBlock(id, block => block.type === "statement" ? fn(block) : block);
  const save = async () => {
    if (!document || !saved) return;
    setBusy(true); setError("");
    try {
      const state = await http.put<HtmlReportState>(path, { expected_token: saved.token, document: editableDocument(document) });
      setSaved(state); setDocument(state.document); setNotice("تم حفظ المحضر بإفاداته وملاحظاته ضمن هذه الجلسة.");
    } catch (err) {
      setError(err instanceof ApiError && err.code === "html_report_changed"
        ? "تغيّر المحضر في نافذة أخرى. لم تُحفظ تعديلاتك فوقه. احتفظ بالنص وأعد تحميل الصفحة."
        : "تعذر حفظ المحضر. تحقق من ربط صاحب الإفادة ومصادر الأسئلة بهذه الجلسة ثم أعد المحاولة.");
    } finally { setBusy(false); }
  };
  const download = () => {
    if (!saved || !catalogue) return;
    const html = renderHtmlReport(saved.document, catalogue, session, { fontDataUrl: font, showSources });
    const url = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
    const link = window.document.createElement("a"); link.href = url; link.download = `report-${session.session_number}.html`; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  const move = (id: string, direction: number) => change(value => {
    const blocks = [...value.blocks]; const index = blocks.findIndex(b => b.id === id); const target = index + direction;
    if (index < 0 || target < 0 || target >= blocks.length) return value;
    [blocks[index], blocks[target]] = [blocks[target], blocks[index]];
    return { ...value, blocks };
  });
  return <div className="html-report-editor" dir="rtl" data-testid="html-report-editor">
    <div className="page-header"><div><h1>المحضر — إفادات وملاحظات</h1><p><Link to={`/investigations/${session.id}`}>{session.title}</Link> · <span className="num">{session.session_number}</span></p></div>
      <button className="btn" disabled={dirty || busy} onClick={onLegacy}>القوالب السابقة والمحاضر الصادرة</button></div>
    {error && <Alert kind="danger">{error}</Alert>}
    {notice && <Alert kind="info">{notice}</Alert>}
    {draft.stale.length > 0 && <Alert kind="warning">تغيّر النص المصدر بعد إعداد المحضر. راجع الأجوبة المرتبطة بالتسجيل قبل الاعتماد عليها.</Alert>}
    {!document || !catalogue ? <Loading /> : <>
      <div className="card"><div className="card-body">
        <div className="form-grid"><Field label="موضوع المحضر"><input className="input" value={document.subject} placeholder={draft.case_subject || session.title} disabled={disabled} onChange={e => change(value => ({ ...value, subject: e.target.value }))} /></Field>
          <Field label="المحقق المسؤول"><select className="select" value={document.investigator_id ?? ""} disabled={disabled} onChange={e => change(value => ({ ...value, investigator_id: e.target.value || null }))}>
            <option value="">اختر من محققي الجلسة</option>{session.investigators.map(i => <option key={i.id} value={i.id}>{[i.rank, i.full_name].filter(Boolean).join(" ")}</option>)}</select></Field></div>
        <div className="flex gap wrap mt-16">
          <button className="btn btn-primary" disabled={disabled} onClick={() => {
            const block = newStatement();
            change(value => ({ ...value, blocks: [...value.blocks, block] })); setSelectedId(block.id);
          }}>+ إضافة إفادة</button>
          <button className="btn btn-primary" disabled={disabled} onClick={() => {
            const block = newNote();
            change(value => ({ ...value, blocks: [...value.blocks, block] })); setSelectedId(block.id);
          }}>+ إضافة ملاحظة</button>
          <button className="btn" disabled={disabled || !dirty} onClick={() => void save()}>{busy ? "جارٍ الحفظ…" : "حفظ المحضر"}</button>
          <button className="btn" disabled={busy || dirty || !document.blocks.length || !font} onClick={download}>تنزيل HTML</button>
          <button className="btn" disabled={busy || dirty || !document.blocks.length || !font} onClick={() => frame.current?.contentWindow?.print()}>طباعة / حفظ PDF</button>
          <span className="small muted">{dirty ? "تغييرات غير محفوظة" : "المعاينة مطابقة للبيانات المحفوظة"} · {document.blocks.filter(b => b.type === "statement").length} إفادة · {document.blocks.filter(b => b.type === "note").length} ملاحظة</span>
        </div>
        <p className="small muted mt-8">أضف إفادة لكل شخص وملاحظة لكل إجراء، ورتّبها حسب تسلسل المحضر. الحقول الصفراء تنتظر التعبئة. الملف المحفوظ هنا مسودة HTML قابلة للطباعة.</p>
        {!editable && <Alert kind="info">هذا المحضر صادر أو متاح للقراءة فقط. إعادة فتح المسودة تتم من شاشة المحاضر الصادرة.</Alert>}
      </div></div>
      {removed && <Alert kind="info">أزيلت {removed.block.type === "note" ? "ملاحظة" : "إفادة"} من المسودة. <button className="btn btn-sm" disabled={disabled} onClick={() => {
        change(value => { const blocks = [...value.blocks]; blocks.splice(Math.min(removed.index, blocks.length), 0, removed.block); return { ...value, blocks }; });
        setSelectedId(removed.block.id); setRemoved(null);
      }}>تراجع عن الإزالة</button></Alert>}
      <div className="html-report-workspace">
        <section className="card html-report-fields"><div className="card-head">الإفادات والملاحظات والحقول المتغيرة</div><div className="card-body">
          <div className="html-statement-list">{document.blocks.map((block, index) => <div className={`html-statement-item ${block.id === selectedId ? "selected" : ""}`} key={block.id}>
            <button className="btn btn-ghost" onClick={() => setSelectedId(block.id)}>{blockLabel(block, index)}</button>
            <div className="flex"><button className="btn btn-sm" aria-label={`نقل ${blockLabel(block, index)} لأعلى`} disabled={disabled || index === 0} onClick={() => move(block.id, -1)}>↑</button><button className="btn btn-sm" aria-label={`نقل ${blockLabel(block, index)} لأسفل`} disabled={disabled || index === document.blocks.length - 1} onClick={() => move(block.id, 1)}>↓</button>
              <button className="btn btn-sm" disabled={disabled} onClick={() => { setRemoved({ block, index }); change(value => ({ ...value, blocks: value.blocks.filter(b => b.id !== block.id) })); if (selectedId === block.id) setSelectedId(null); }}>إزالة</button></div>
          </div>)}</div>
          {active ? <>
            {active.type === "statement" && <Field label="ربط صاحب الإفادة بمتحدث من الجلسة"><select className="select" disabled={disabled} value={active.speaker_id ?? ""} onChange={e => {
              const next = e.target.value || null;
              if (active.speaker_id === next) return;
              if ((Object.values(active.values).some(Boolean) || active.entries.some(entry => entry.question || entry.answer)) && !window.confirm("تغيير صاحب الإفادة يمسح حقول هذا الشخص وأجوبته من هذه الكتلة. لإضافة شخص آخر استخدم إضافة إفادة. هل تريد التغيير؟")) return;
              const speaker = draft.speakers.find(s => s.id === next);
              updateStatement(active.id, block => ({ ...block, speaker_id: next, values: { statement_name: speaker?.person_name || speaker?.display_name || "" }, entries: [newEntry()], identity_checked: false, attestation_confirmed: false }));
            }}><option value="">إفادة تُملأ يدوياً</option>{draft.speakers.map(s => <option key={s.id} value={s.id}>{s.report_name} · {s.speaker_label}</option>)}</select></Field>}
            {active.type === "note" && <p className="small muted">اكتب المراجعة أو القرار أو الإجراء في نص الملاحظة. لكل ملاحظة تاريخها وتوقيعاتها، ويمكن نقلها بين الإفادات باستخدام الأسهم.</p>}
            {[...new Set((activeFields || []).map(field => field.group))].map(group => <details open key={group} className="html-field-group"><summary>{group}</summary><div className="form-grid">
              {(activeFields || []).filter(field => field.group === group).map(field => <Field key={field.key} label={field.label} full={field.multiline}>
                {field.multiline ? <textarea className="textarea" rows={field.key === "note_text" ? 8 : 3} maxLength={field.key === "note_text" ? 40000 : 10000} disabled={disabled} value={active.values[field.key] ?? ""} aria-label={field.label} onChange={e => updateBlock(active.id, block => ({ ...block, values: { ...block.values, [field.key]: e.target.value } }))} />
                  : <input className="input" disabled={disabled} value={active.values[field.key] ?? ""} aria-label={field.label} maxLength={2000} onChange={e => updateBlock(active.id, block => ({ ...block, values: { ...block.values, [field.key]: e.target.value } }))} />}
              </Field>)}
            </div></details>)}
            {active.type === "statement" && <>
            <div className="html-field-group"><b>عبارات الوقائع</b><label className="checkbox"><input type="checkbox" disabled={disabled} checked={active.identity_checked} onChange={e => updateStatement(active.id, b => ({ ...b, identity_checked: e.target.checked }))} />إدراج عبارة التحقق من الوثائق وإعادتها بعد حصول ذلك</label>
              <label className="checkbox"><input type="checkbox" disabled={disabled} checked={active.attestation_confirmed} onChange={e => updateStatement(active.id, b => ({ ...b, attestation_confirmed: e.target.checked }))} />إدراج عبارة تلاوة الإفادة وتصديقها والتوقيع عليها بعد حصول ذلك</label></div>
            <div className="flex gap wrap"><h3>نص الإفادة — س.ج</h3><button className="btn btn-sm" disabled={disabled || !active.speaker_id} onClick={() => updateStatement(active.id, block => importAnswers(block, draft.qa_blocks))}>إدراج أسئلة وأجوبة هذا المتحدث</button></div>
            {active.entries.map((entry, index) => <div className="html-answer-editor" key={entry.id}>
              <b>الفقرة {index + 1}</b><Field label="السؤال (اختياري)"><textarea className="textarea" rows={2} disabled={disabled} value={entry.question} onChange={e => updateStatement(active.id, b => ({ ...b, entries: b.entries.map(row => row.id === entry.id ? { ...row, question: e.target.value } : row) }))} /></Field>
              <Field label="الجواب / نص الإفادة"><textarea className="textarea" rows={4} disabled={disabled} value={entry.answer} onChange={e => updateStatement(active.id, b => ({ ...b, entries: b.entries.map(row => row.id === entry.id ? { ...row, answer: e.target.value } : row) }))} /></Field>
              {entry.source_block_ids.length > 0 && <p className="small muted">مرتبط بمصدره في النص المنقح. التعديل هنا يغيّر مسودة المحضر.</p>}
              <button className="btn btn-sm" disabled={disabled} onClick={() => updateStatement(active.id, b => ({ ...b, entries: b.entries.filter(row => row.id !== entry.id) }))}>إزالة الفقرة</button>
            </div>)}
            <button className="btn" disabled={disabled} onClick={() => updateStatement(active.id, b => ({ ...b, entries: [...b.entries, newEntry()] }))}>+ إضافة سؤال / جواب</button>
            </>}
          </> : <p className="muted">اختر إفادة أو ملاحظة لتعبئة حقولها، أو أضف واحدة جديدة.</p>}
        </div></section>
        <section className="card html-report-preview"><div className="card-head">معاينة HTML المباشرة</div><div className="card-body flex gap wrap">
          <label className="checkbox"><input type="checkbox" checked={highlight} onChange={e => setHighlight(e.target.checked)} />تمييز الحقول المتغيرة</label>
          <label className="checkbox"><input type="checkbox" checked={showSources} onChange={e => setShowSources(e.target.checked)} />إظهار ثواني المصدر</label>
        </div><iframe ref={frame} title="معاينة محضر الإفادات والملاحظات" srcDoc={preview} sandbox="allow-same-origin allow-modals" /></section>
      </div>
    </>}
  </div>;
}
