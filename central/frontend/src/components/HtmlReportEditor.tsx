import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, getToken, http } from "@/api/client";
import { errorMessage } from "@/lib/i18n";
import type { Investigation, ReportDraft } from "@/api/types";
import { Alert, Field, Loading } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { useReportDraft } from "@/lib/useReportDraft";
import { ReportIssuance } from "./ReportIssuance";
import { IntakeReadiness } from "./IntakeReadiness";
import { ReportDictation, type DictationTarget } from "./ReportDictation";
import { attention, ReportSectionEditor } from "./ReportSectionEditor";
import { blockLabel, editableDocument, newEntry, newNote, newConclusion, selectionPayload,
  type HtmlReportState, type ReportBlock, type StatementBlock, type StatementCatalogue, type ReportPersonOption, type NoteTemplate } from "@/lib/html-report";

export function HtmlReportEditor({ session, editable, onStatusChange, onDirtyChange }: {
  session: Investigation; draft: ReportDraft; editable: boolean; onStatusChange: () => void;
  onDirtyChange: (id: string, dirty: boolean) => void;
}) {
  const { can, user } = useAuth();
  const path = `/investigations/${session.id}/report/html`;
  const store = useReportDraft(path, editable);
  const { saved, document, dirty, saving, change, accept, flush } = store;
  const [catalogue, setCatalogue] = useState<StatementCatalogue | null>(null);
  const [people, setPeople] = useState<ReportPersonOption[]>([]);
  const [templates, setTemplates] = useState<NoteTemplate[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [focusField, setFocusField] = useState<string | null>(null);
  const [preview, setPreview] = useState("");
  const [previewError, setPreviewError] = useState(false);
  const [pdf, setPdf] = useState<string | null>(null);
  const [mode, setMode] = useState<"write" | "review">("write");
  const [mobilePane, setMobilePane] = useState<"outline" | "edit" | "preview">("edit");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [picker, setPicker] = useState(false);
  const [chosen, setChosen] = useState<string[]>([]);
  const [additional, setAdditional] = useState(false);
  const [removed, setRemoved] = useState<{ block: ReportBlock; index: number } | null>(null);
  const [comparison, setComparison] = useState<{ current: StatementBlock; proposed: StatementBlock } | null>(null);
  const [dictation, setDictation] = useState<DictationTarget | null>(null);
  const [conflictChoices, setConflictChoices] = useState<Record<string, "local" | "server">>({});
  const [headerChoice, setHeaderChoice] = useState<"local" | "server">("local");
  const frame = useRef<HTMLIFrameElement>(null);
  const scroll = useRef(0);
  const selectedRef = useRef(selected); selectedRef.current = selected;
  const disabled = !editable || busy || saved?.status === "FINAL" || !!store.conflict;
  const intakeBlocked = session.intake_readiness?.ready === false;
  const voiceAllowed = can("reports.generate") && session.investigators.some(i => i.id === user?.profile?.id);
  const isLead = can("reports.finalize") && session.investigators.some(i => i.id === user?.profile?.id && i.assignment_role === "LEAD");
  const active = document?.blocks.find(b => b.id === selected);
  const issues = document?.blocks.flatMap(attention) ?? [];
  const select = (id: string, field?: string) => { setSelected(id); setFocusField(field ?? null); setMobilePane("edit"); setMode("write"); };
  useEffect(() => {
    let stopped = false;
    void Promise.all([http.get<HtmlReportState>(path), http.get<StatementCatalogue>("/report-forms/html-statement"),
      http.get<{ session_id: string; options: ReportPersonOption[] }>(`${path}/people`), http.get<NoteTemplate[]>("/report-forms/note-templates")])
      .then(([state, form, participants, notes]) => {
        if (stopped) return;
        if (state.document.session_id !== session.id || participants.session_id !== session.id) throw new Error("session mismatch");
        accept(state); setCatalogue(form); setPeople(participants.options); setTemplates(notes); setSelected(state.document.blocks[0]?.id ?? null);
      }).catch(() => { if (!stopped) setError("تعذر تحميل المحضر. تحقق من الاتصال وأعد تحميل الصفحة."); });
    return () => { stopped = true; };
  }, [path, accept]);
  useEffect(() => { onDirtyChange("html-report", dirty || saving || busy || !!dictation); }, [dirty, saving, busy, dictation, onDirtyChange]);
  useEffect(() => () => onDirtyChange("html-report", false), [onDirtyChange]);
  useEffect(() => {
    if (!document || !saved || saving) return;
    let stopped = false;
    const timer = window.setTimeout(() => {
      void http.post<{ html: string }>(`${path}/preview`, { expected_token: saved.token, document: editableDocument(document) })
        .then(value => { if (!stopped) { scroll.current = frame.current?.contentWindow?.scrollY ?? scroll.current; setPreview(value.html); setPreviewError(false); } })
        .catch(() => { if (!stopped) setPreviewError(true); });
    }, 450);
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [document, saved?.token, saving, path]);
  useEffect(() => {
    if (!focusField || !selected) return;
    const element = window.document.getElementById(`report-field-${selected}-${focusField}`);
    if (element) {
      for (let parent: HTMLElement | null = element; parent; parent = parent.parentElement) if (parent instanceof HTMLDetailsElement) parent.open = true;
      element.scrollIntoView({ block: "center", behavior: "smooth" }); element.focus();
    }
    setFocusField(null);
  }, [selected, focusField, mode]);
  useEffect(() => {
    frame.current?.contentDocument?.querySelectorAll("[data-block-id]").forEach(element => element.classList.toggle("selected", element.getAttribute("data-block-id") === selected));
  }, [selected, preview]);
  useEffect(() => { setPdf(null); }, [saved?.token, saved?.source_token]);
  useEffect(() => () => { if (pdf) URL.revokeObjectURL(pdf); }, [pdf]);
  const frameLoaded = () => {
    const doc = frame.current?.contentDocument;
    if (!doc) return;
    frame.current?.contentWindow?.scrollTo(0, scroll.current);
    doc.querySelectorAll<HTMLElement>("[data-block-id]").forEach(element => {
      element.classList.toggle("selected", element.dataset.blockId === selectedRef.current);
      const activate = (event: Event) => {
        const target = event.target as HTMLElement;
        const entry = target.closest<HTMLElement>("[data-entry-id]")?.dataset.entryId;
        select(element.dataset.blockId!, entry ? `answer-${entry}` : target.closest<HTMLElement>("[data-field]")?.dataset.field);
      };
      element.addEventListener("click", activate);
      element.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(event); } });
    });
  };
  const operation = async (fn: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await fn(); } catch (err) { setError(err instanceof ApiError ? errorMessage(err.code) : err instanceof Error ? err.message : "تعذر إتمام الإجراء؛ احتُفظ بتعديلاتك."); }
    finally { setBusy(false); }
  };
  const replace = (block: ReportBlock) => change(v => ({ ...v, blocks: v.blocks.map(b => b.id === block.id ? block : b) }));
  const insert = (blocks: ReportBlock[]) => {
    change(value => { const next = [...value.blocks]; const index = selected ? next.findIndex(b => b.id === selected) + 1 : next.length;
      next.splice(index, 0, ...blocks); return { ...value, blocks: next }; });
    if (blocks[0]) select(blocks[0].id, blocks[0].type === "note" ? "note_text" : undefined);
  };
  const defaults = () => ({ closing_date: session.session_date ?? "", closing_location: session.location ?? "" });
  const addConclusion = () => {
    const existing = document?.blocks.find(b => b.type === "conclusion");
    if (existing) { select(existing.id, "facts"); return; }
    const block = newConclusion(); block.values = defaults();
    change(v => ({ ...v, blocks: [...v.blocks, block] })); select(block.id, "facts");
  };
  const prepare = () => operation(async () => {
    let state = await flush();
    if (state.sources_changed) {
      state = await http.post<HtmlReportState>(`${path}/refresh-sources`, { expected_token: state.token });
      accept(state);
    }
    const response = await http.post<{ blocks: StatementBlock[] }>(`${path}/prepare-statements`, { expected_token: state.token, participant_keys: chosen, allow_additional: additional });
    insert(response.blocks.map(b => ({ ...b, entries: b.entries.length ? b.entries : [newEntry()] })));
    setPicker(false); setChosen([]); setAdditional(false);
  });
  const compare = () => operation(async () => {
    if (active?.type !== "statement") return;
    const state = await flush();
    // Refresh the import catalogue only. Existing statement wording remains unchanged.
    accept(await http.post<HtmlReportState>(`${path}/refresh-sources`, { expected_token: state.token }));
    const proposed = await http.post<StatementBlock>(`${path}/statement-preview`, selectionPayload({ participant_key: active.participant_key ?? null, identity_id: active.identity_id ?? null, speaker_id: active.speaker_id }));
    setComparison({ current: active, proposed });
  });
  const openPdf = () => operation(async () => {
    const state = await flush();
    const response = await fetch(`/api${path}/preview-pdf`, { method: "POST", headers: { Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" },
      body: JSON.stringify({ expected_token: state.token, document: editableDocument(state.document) }) });
    if (!response.ok) throw new Error("تعذر إنشاء PDF. بقيت المسودة محفوظة؛ أعد المحاولة.");
    setPdf(URL.createObjectURL(await response.blob())); setMode("review");
  });
  const move = (id: string, delta: number) => change(v => {
    const blocks = [...v.blocks], index = blocks.findIndex(b => b.id === id), next = index + delta;
    if (next < 0 || next >= blocks.length) return v;
    [blocks[index], blocks[next]] = [blocks[next], blocks[index]]; return { ...v, blocks };
  });
  const showBlock = (block?: ReportBlock) => block ? <><p>{Object.values(block.values).join(" · ")}</p>{block.type === "statement" && block.entries.map(e => <p className="preserve-lines" key={e.id}>{e.question}<br />{e.answer}</p>)}{block.type === "conclusion" && <><p>المسؤوليات: {block.responsibility_mode} — الاقتراحات: {block.proposal_mode}</p>{block.findings.map(f => <p key={f.id}>{f.subject_snapshot || f.unidentified_subject} {f.text}</p>)}</>}<details><summary>كل الحقول والمراجع</summary><pre>{JSON.stringify(block, null, 2)}</pre></details></> : <p>أزيل القسم</p>;
  return <div className="html-report-editor report-studio" dir="rtl" data-testid="html-report-editor">
    <header className="page-header"><div><h1>محضر التحقيق</h1><p><Link to={`/investigations/${session.id}`}>{session.title}</Link> · <bdi>{session.session_number}</bdi></p></div>
      <div className="report-save-state" role="status" aria-live="polite">{store.error ? "تعذر الحفظ" : saving ? "جارٍ الحفظ…" : dirty ? "تغييرات بانتظار الحفظ" : "تم الحفظ"}</div></header>
    <IntakeReadiness session={session} />
    {(error || store.error) && <Alert kind="danger">{error || store.error}{store.error && !store.conflict && <button className="btn" onClick={() => void store.retry().catch(() => undefined)}>إعادة محاولة الحفظ</button>}</Alert>}
    {!document || !catalogue || !saved ? <Loading /> : <>
      <section className="card card-body report-context"><div className="form-grid">
        <Field label="موضوع المحضر"><input className="input" value={document.subject} disabled={disabled} onChange={e => change(v => ({ ...v, subject: e.target.value }))} /></Field>
        <Field label="المحقق المسؤول"><select className="select" value={document.investigator_id ?? ""} disabled={disabled} onChange={e => change(v => ({ ...v, investigator_id: e.target.value || null }))}>
          <option value="">اختر المحقق</option>{session.investigators.map(i => <option key={i.id} value={i.id}>{[i.rank, i.full_name].filter(Boolean).join(" ")}</option>)}</select></Field>
        <Field label="الكاتب العدلي"><select className="select" value={document.clerk_id ?? ""} disabled={disabled} onChange={e => change(v => ({ ...v, clerk_id: e.target.value || null }))}>
          <option value="">اختر الكاتب عند التكليف</option>{session.investigators.map(i => <option key={i.id} value={i.id}>{[i.rank, i.full_name].filter(Boolean).join(" ")}</option>)}</select></Field>
      </div><div className="report-toolbar">
        <button className="btn btn-primary" disabled={disabled || intakeBlocked} onClick={() => { setPicker(true); setChosen([]); }}>إضافة إفادة</button>
        <button className="btn btn-primary" disabled={disabled || intakeBlocked} onClick={() => { const b = newNote(); b.values = { ...defaults(), note_date: "", note_time: "" }; insert([b]); }}>إضافة ملاحظة</button>
        <button className="btn btn-primary" disabled={disabled || intakeBlocked} onClick={addConclusion}>خلاصة التحقيق</button>
        <button className="btn" disabled={disabled || !dirty || saving} onClick={() => void store.retry().catch(() => undefined)}>حفظ الآن</button>
        <button className="btn" aria-pressed={mode === "write"} onClick={() => setMode("write")}>الكتابة</button>
        <button className="btn" disabled={busy || !!store.error} onClick={() => void openPdf()}>معاينة PDF والمراجعة</button>
      </div></section>
      {picker && <section className="card card-body" aria-label="اختيار أصحاب الإفادات"><h2>اختر أصحاب الإفادات</h2><p>تُستورد بيانات الأشخاص وأقوالهم المراجعة من هذه الجلسة في خطوة واحدة.</p>
        <label className="checkbox"><input type="checkbox" checked={additional} onChange={e => { setAdditional(e.target.checked); setChosen([]); }} />إضافة إفادة أخرى لشخص لديه إفادة محفوظة</label>
        {people.filter(p => p.participant_key).map(p => {
          const exists = document.blocks.some(b => b.type === "statement" && b.participant_key === p.participant_key);
          return <label className="checkbox" key={p.key}><input type="checkbox" disabled={disabled || (exists && !additional)} checked={chosen.includes(p.participant_key!)} onChange={e => setChosen(v => e.target.checked ? [...v, p.participant_key!] : v.filter(k => k !== p.participant_key))} />{p.label} {exists && <span className="muted">— له إفادة</span>}</label>;
        })}<div className="flex gap wrap"><button className="btn btn-primary" disabled={disabled || !chosen.length} onClick={() => void prepare()}>تجهيز الإفادات المحددة ({chosen.length})</button><button className="btn" onClick={() => setPicker(false)}>إلغاء</button></div>
      </section>}
      {store.conflict && <section className="card card-body" aria-label="مصالحة تعارض الحفظ"><h2>قارن النسختين واختر لكل قسم</h2>
        <div className="report-compare"><p>نسختي: {document.subject}</p><p>المحفوظة: {store.conflict.document.subject}</p></div>
        <Field label="عنوان المحضر والتكليفات"><select className="select" value={headerChoice} onChange={e => setHeaderChoice(e.target.value as "local" | "server")}><option value="local">بيانات نسختي الحالية</option><option value="server">بيانات النسخة المحفوظة</option></select></Field>
        {[...new Set([...document.blocks.map(b => b.id), ...store.conflict.document.blocks.map(b => b.id)])].map(id => <div key={id}>
          <div className="report-compare"><div><h3>نسختي</h3>{showBlock(document.blocks.find(b => b.id === id))}</div><div><h3>المحفوظة</h3>{showBlock(store.conflict!.document.blocks.find(b => b.id === id))}</div></div>
          <select className="select" aria-label="النسخة المعتمدة للقسم" value={conflictChoices[id] ?? ""} onChange={e => setConflictChoices(v => ({ ...v, [id]: e.target.value as "local" | "server" }))}><option value="" disabled>اختر بعد المقارنة</option><option value="local">استخدام نسختي لهذا القسم</option><option value="server">استخدام النسخة المحفوظة لهذا القسم</option></select>
        </div>)}<button className="btn btn-primary" disabled={[...new Set([...document.blocks.map(b => b.id), ...store.conflict.document.blocks.map(b => b.id)])].some(id => !conflictChoices[id])}
          onClick={() => { store.reconcile(conflictChoices, headerChoice); setConflictChoices({}); }}>اعتماد الاختيارات وحفظ النسخة الموحّدة</button>
      </section>}
      {comparison && <section className="card card-body" aria-label="مقارنة الإفادة بالمصدر"><h2>الإفادة الحالية والمصدر المراجع</h2>
        <div className="report-compare"><div><h3>النص الحالي</h3>{showBlock(comparison.current)}</div><div><h3>المصدر</h3>{showBlock(comparison.proposed)}</div></div>
        <button className="btn btn-primary" disabled={disabled} onClick={() => { replace({ ...comparison.proposed, id: comparison.current.id, identity_checked: false, attestation_confirmed: false,
          entries: comparison.proposed.entries.length ? comparison.proposed.entries : [newEntry()] }); setComparison(null); }}>قبول استبدال هذه الإفادة بالمصدر</button><button className="btn" onClick={() => setComparison(null)}>الاحتفاظ بالنص الحالي</button>
      </section>}
      {removed && <Alert kind="info">أزيل القسم من المسودة. <button className="btn" disabled={disabled} onClick={() => { change(v => { const blocks = [...v.blocks]; blocks.splice(Math.min(removed.index, blocks.length), 0, removed.block); return { ...v, blocks }; }); select(removed.block.id); setRemoved(null); }}>تراجع عن الإزالة</button></Alert>}
      {mode === "review" ? <section className="report-review"><h2>المعاينة النهائية — PDF</h2><p>هذه المعاينة تستخدم محرّك الإصدار نفسه. النسخة غير الصادرة تحمل علامة مسودة.</p>
        {pdf && <><a className="btn" href={pdf} download={`draft-${session.session_number}.pdf`}>تنزيل المعاينة PDF</a><iframe className="report-pdf-frame" src={pdf} title="معاينة PDF النهائية" /></>}
        {!pdf && <button className="btn" onClick={() => void openPdf()}>إنشاء المعاينة الحالية</button>}
        {issues.length > 0 && <div className="card card-body"><h3>أكمل قبل الإصدار</h3>{issues.map((issue, i) => <button className="btn report-attention" key={`${issue.block}-${issue.field}-${i}`} onClick={() => select(issue.block, issue.field)}>{issue.label} — {blockLabel(document.blocks.find(b => b.id === issue.block)!, document.blocks.findIndex(b => b.id === issue.block))}</button>)}</div>}
        <ReportIssuance sessionId={session.id} state={saved} blocked={dirty || busy || saving || !!dictation || !pdf} canApprove={isLead} onState={accept} onStatusChange={onStatusChange} />
      </section> : <>
        <nav className="report-mobile-tabs" aria-label="أجزاء مساحة المحضر">{([['outline', 'الأقسام'], ['edit', 'الكتابة'], ['preview', 'المحضر']] as const).map(([key, label]) => <button className="btn" key={key} aria-pressed={mobilePane === key} onClick={() => setMobilePane(key)}>{label}</button>)}</nav>
        <div className={`report-studio-grid show-${mobilePane}`}>
          <aside className="card report-outline" aria-label="أقسام المحضر"><div className="card-head">أقسام المحضر <span>{document.blocks.length}</span></div><div className="card-body">
            {!document.blocks.length && <p>ابدأ باختيار أصحاب الإفادات، ثم أضف الملاحظات والخلاصة.</p>}
            {document.blocks.map((block, index) => <div className={`report-outline-item ${selected === block.id ? "selected" : ""}`} key={block.id}>
              <button className="btn btn-ghost" aria-current={selected === block.id ? "true" : undefined} onClick={() => select(block.id)}>{blockLabel(block, index)}{attention(block).length > 0 && <span className="report-needs">يحتاج استكمالاً</span>}</button>
              <div className="flex gap"><button className="btn btn-sm" aria-label={`نقل ${blockLabel(block, index)} لأعلى`} disabled={disabled || index === 0} onClick={() => move(block.id, -1)}>↑</button><button className="btn btn-sm" aria-label={`نقل ${blockLabel(block, index)} لأسفل`} disabled={disabled || index === document.blocks.length - 1} onClick={() => move(block.id, 1)}>↓</button>
                <button className="btn btn-sm" disabled={disabled} onClick={() => { setRemoved({ block, index }); change(v => ({ ...v, blocks: v.blocks.filter(b => b.id !== block.id) })); setSelected(document.blocks[index + 1]?.id ?? document.blocks[index - 1]?.id ?? null); }}>إزالة</button></div>
            </div>)}{!document.blocks.some(b => b.type === "conclusion") && <button className="btn report-attention" disabled={disabled || intakeBlocked} onClick={addConclusion}>أضف خلاصة التحقيق</button>}
          </div></aside>
          <section className="card report-paper"><div className="card-head">المحضر — اضغط القسم لتعديله</div>{previewError && <p role="status">تعذر تحديث المعاينة؛ آخر معاينة ناجحة باقية.</p>}
            <iframe ref={frame} title="محضر التحقيق — اضغط للتعديل" srcDoc={preview} onLoad={frameLoaded} sandbox="allow-same-origin allow-modals" /></section>
          <section className="card report-edit-panel"><div className="card-head">{active ? blockLabel(active, document.blocks.indexOf(active)) : "الكتابة"}</div><div className="card-body">
            {active ? <ReportSectionEditor key={active.id} block={active} blocks={document.blocks} session={session} catalogue={catalogue} templates={templates} disabled={disabled} canManage={can("reports.templates.manage")} voiceAllowed={voiceAllowed}
              onChange={replace} onTemplate={t => setTemplates(v => [...v, t])} onVoice={target => { if (!dictation) setDictation(target); else setError("أكمل التسجيل المفتوح أو أغلقه قبل تغيير حقل الإملاء."); }} onRefresh={() => void compare()} /> : <p className="muted">اختر قسماً من المحضر أو أضف إفادة أو ملاحظة.</p>}
          </div></section>
        </div>
      </>}
      {voiceAllowed && <ReportDictation sessionId={session.id} target={dictation} disabled={disabled} flush={flush} onState={accept} onClose={() => setDictation(null)} onBusy={setBusy} />}
    </>}
  </div>;
}
