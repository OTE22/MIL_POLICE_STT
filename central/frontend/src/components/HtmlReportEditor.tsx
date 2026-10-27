import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, getToken, http } from "@/api/client";
import { errorMessage } from "@/lib/i18n";
import type { Investigation, ReportDraft } from "@/api/types";
import { Alert, Field, Loading, Modal } from "@/components/ui";
import { IconMic, IconPlus, IconShield } from "./Icons";
import { useAuth } from "@/lib/auth";
import { useReportDraft } from "@/lib/useReportDraft";
import { ReportIssuance } from "./ReportIssuance";
import { ReportOpeningEditor } from "./ReportOpeningEditor";
import { editReportText, ReportDocumentEditor } from "./ReportDocumentEditor";
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
  const [mode, setMode] = useState<"write" | "document" | "review">("write");
  const [mobilePane, setMobilePane] = useState<"outline" | "edit" | "preview">("edit");
  const [showPreview, setShowPreview] = useState(false);
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
  if (document) {
    if (document.closing) {
      for (const [field, label] of [["text", "نص ختام المحضر"], ["location", "مكان ختام المحضر"], ["date", "تاريخ ختام المحضر"]] as const) {
        if (!document.closing[field]?.trim()) issues.push({ block: "closing", field, label });
      }
    }
    const needOpening = (field: string, label: string, ready: unknown) => { if (!ready) issues.push({ block: "opening", field, label }); };
    needOpening("subject", "موضوع المحضر", document.subject.trim());
    needOpening("investigator_id", "المحقق المسؤول", document.investigator_id);
    needOpening("clerk_id", "كاتب عدلي مختلف عن المحقق", document.clerk_id && document.clerk_id !== document.investigator_id);
    needOpening("session_context", "تاريخ الجلسة ووقتها ومكانها", session.session_date && session.start_time && session.location);
    needOpening("profile_context", "وحدة المحقق ورقم الكاتب", session.investigators.find(i => i.id === document.investigator_id)?.unit && session.investigators.find(i => i.id === document.clerk_id)?.military_id);
    for (const [field, label] of [["referral_number", "رقم الإحالة"], ["referral_date", "تاريخ الإحالة"], ["referral_authority", "الجهة المحيلة"], ["oath_confirmed", "تأكيد اليمين"], ["uniform_confirmed", "تأكيد اللباس العسكري"]] as const) {
      const value = document.opening?.[field];
      if (!value || (typeof value === "string" && !value.trim())) issues.push({ block: "opening", field, label });
    }
  }
  const select = (id: string, field?: string) => { setSelected(id); setFocusField(field ?? null); setMobilePane("edit"); setMode("write"); };
  useEffect(() => {
    if (showPreview) frame.current?.closest("section")?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [showPreview]);
  useEffect(() => {
    let stopped = false;
    void Promise.all([http.get<HtmlReportState>(path), http.get<StatementCatalogue>("/report-forms/html-statement"),
      http.get<{ session_id: string; options: ReportPersonOption[] }>(`${path}/people`), http.get<NoteTemplate[]>("/report-forms/note-templates")])
      .then(([state, form, participants, notes]) => {
        if (stopped) return;
        if (state.document.session_id !== session.id || participants.session_id !== session.id) throw new Error("session mismatch");
        accept(state); setCatalogue(form); setPeople(participants.options); setTemplates(notes); setSelected("opening");
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
  const addConclusion = (field = "facts") => {
    const existing = document?.blocks.find(b => b.type === "conclusion");
    if (existing) { select(existing.id, field); return; }
    const block = newConclusion(); block.values = defaults();
    change(v => ({ ...v, blocks: [...v.blocks, block] })); select(block.id, field);
  };
  const addClosing = () => {
    if (!document?.closing) change(v => ({ ...v, closing: {
      text: "نظم وختم هذا التحقيق بصورته الحاضرة ووقع من قبلنا نحن والكاتب العدلي، للتفضل بالاطلاع.",
      location: session.location ?? "", date: session.session_date ?? null,
    } }));
    select("closing");
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
    setMode("review");
    const state = await flush();
    const response = await fetch(`/api${path}/preview-pdf`, { method: "POST", headers: { Authorization: `Bearer ${getToken()}`, "Content-Type": "application/json" },
      body: JSON.stringify({ expected_token: state.token, document: editableDocument(state.document) }) });
    if (!response.ok) throw new Error("تعذر إنشاء PDF. بقيت المسودة محفوظة؛ أعد المحاولة.");
    const file = await response.blob();
    if (!file.type.includes("application/pdf") || file.size === 0) throw new Error("استجاب الخادم بملف غير صالح للمعاينة. أعد المحاولة.");
    setPdf(URL.createObjectURL(file));
  });
  const move = (id: string, delta: number) => change(v => {
    const blocks = [...v.blocks], index = blocks.findIndex(b => b.id === id), next = index + delta;
    if (next < 0 || next >= blocks.length) return v;
    [blocks[index], blocks[next]] = [blocks[next], blocks[index]]; return { ...v, blocks };
  });
  const showBlock = (block?: ReportBlock) => block ? <><p>{Object.values(block.values).join(" · ")}</p>{block.type === "statement" && block.entries.map(e => <p className="preserve-lines" key={e.id}>{e.question}<br />{e.answer}</p>)}{block.type === "conclusion" && <><p>المسؤوليات: {block.responsibility_mode} — الاقتراحات: {block.proposal_mode}</p>{block.findings.map(f => <p key={f.id}>{f.subject_snapshot || f.unidentified_subject} {f.text}</p>)}</>}<details><summary>كل الحقول والمراجع</summary><pre>{JSON.stringify(block, null, 2)}</pre></details></> : <p>أزيل القسم</p>;
  return <div className="html-report-editor report-studio" dir="rtl" data-testid="html-report-editor">
    <header className="page-header report-command-header"><div><Link className="report-back" to={`/investigations/${session.id}`}>العودة إلى جلسة التحقيق ←</Link><div className="report-title-line"><span className="report-emblem"><IconShield /></span><h1>مساحة إعداد المحضر</h1><span className="report-state-badge">{saved?.status === "FINAL" ? "صادر" : "مسودة"}</span></div><p>{session.title} · <bdi>{session.session_number}</bdi></p></div>
      <div className={`report-save-state ${store.error ? "save-error" : ""}`} role="status" aria-live="polite"><span aria-hidden="true" className="report-status-dot" />{!saved ? "جارٍ التحميل…" : store.error ? "تعذر الحفظ" : saving ? "جارٍ الحفظ…" : dirty ? "تغييرات بانتظار الحفظ" : "تم الحفظ"}<small>حفظ تلقائي أثناء الكتابة</small></div></header>
    <IntakeReadiness session={session} />
    {(error || store.error) && <Alert kind="danger">{error || store.error}{store.error && !store.conflict && <button className="btn" onClick={() => void store.retry().catch(() => undefined)}>إعادة محاولة الحفظ</button>}</Alert>}
    {!document || !catalogue || !saved ? <Loading /> : <>
      <nav className="report-workflow" aria-label="مراحل إعداد المحضر">
        <button aria-current={mode === "write" && selected === "opening" ? "step" : undefined} onClick={() => select("opening")}><span>01</span><div><strong>افتتاح المحضر</strong><small>الإحالة والتكليفات</small></div></button>
        <button aria-current={mode === "write" && selected !== "opening" ? "step" : undefined} onClick={() => { if (document.blocks[0]) select(document.blocks[0].id); else { setMode("write"); setPicker(true); } }}><span>02</span><div><strong>الإفادات والملاحظات</strong><small>{document.blocks.length} أقسام · الخلاصة</small></div></button>
        <button aria-current={mode === "review" ? "step" : undefined} disabled={busy || !!store.error} onClick={() => void openPdf()}><span>03</span><div><strong>المراجعة والإصدار</strong><small>فحص النسخة النهائية</small></div></button>
      </nav>
      <details className="card report-context" open={selected === "opening" && mode === "write"}>
        <summary><span>بيانات المحضر والتكليفات</span><small>{session.investigators.find(i => i.id === document.investigator_id)?.full_name || "اختر المحقق"} · {document.clerk_id ? "الكاتب محدد" : "الكاتب غير محدد"}</small></summary><div className="card-body form-grid">
        <Field label="موضوع المحضر"><input id="report-field-opening-subject" className="input" value={document.subject} disabled={disabled} onChange={e => change(v => ({ ...v, subject: e.target.value }))} /></Field>
        <Field label="المحقق المسؤول"><select id="report-field-opening-investigator_id" className="select" value={document.investigator_id ?? ""} disabled={disabled} onChange={e => change(v => ({ ...v, investigator_id: e.target.value || null }))}>
          <option value="">اختر المحقق</option>{session.investigators.map(i => <option key={i.id} value={i.id}>{[i.rank, i.full_name].filter(Boolean).join(" ")}</option>)}</select></Field>
        <Field label="الكاتب العدلي"><select id="report-field-opening-clerk_id" className="select" value={document.clerk_id ?? ""} disabled={disabled} onChange={e => change(v => ({ ...v, clerk_id: e.target.value || null, opening: { ...v.opening, oath_confirmed: false } }))}>
          <option value="">اختر الكاتب عند التكليف</option>{session.investigators.map(i => <option key={i.id} value={i.id}>{[i.rank, i.full_name].filter(Boolean).join(" ")}</option>)}</select></Field>
      </div></details><div className="report-toolbar" aria-label="أدوات المحضر">
        <div className="report-add-actions"><button className="btn btn-primary" disabled={disabled || intakeBlocked} onClick={() => { setPicker(true); setChosen([]); }}><IconPlus /> إضافة إفادة</button>
        <button className="btn btn-primary" disabled={disabled || intakeBlocked} onClick={() => { const b = newNote(); b.values = { ...defaults(), note_date: "", note_time: "" }; insert([b]); }}>إضافة ملاحظة</button>
        <button className="btn" disabled={disabled || intakeBlocked} onClick={() => addConclusion()}>خلاصة التحقيق</button>
        <button className="btn" disabled={disabled || intakeBlocked} onClick={() => addConclusion("responsibility_mode")}>المسؤوليات</button>
        <button className="btn" disabled={disabled || intakeBlocked} onClick={() => addConclusion("proposal_mode")}>الاقتراحات</button>
        <button className="btn" disabled={disabled || intakeBlocked} onClick={addClosing}>ختام المحضر</button></div>
        <div className="report-view-actions">
        <button className="btn" disabled={disabled || !dirty || saving} onClick={() => void store.retry().catch(() => undefined)}>حفظ الآن</button>
        <button className="btn" aria-pressed={mode === "write"} onClick={() => setMode("write")}>الكتابة</button>
        <button className="btn" aria-pressed={mode === "document"} onClick={() => setMode("document")}>تحرير المحضر قبل الطباعة</button>
        <button className="btn" aria-pressed={showPreview && mode === "write"} onClick={() => { setShowPreview(v => !v); setMode("write"); setMobilePane(showPreview ? "edit" : "preview"); }}>{showPreview ? "إخفاء معاينة المحضر" : "معاينة أثناء الكتابة"}</button>
        <button className="btn" disabled={busy || !!store.error} onClick={() => void openPdf()}>معاينة PDF والمراجعة</button></div>
      </div>
      <details className="report-voice-guide" aria-label="الكتابة بالصوت" data-testid="report-voice-guide">
        <summary><IconMic /><strong>الكتابة بالصوت</strong><span>{voiceAllowed ? "إملاء الملاحظات والخلاصة · سجّل ثم راجع النص" : "متاحة للمحقق المكلّف · تفاصيل الصلاحية"}</span></summary><div>
        {voiceAllowed ? <>
          <p>اختر ملاحظة أو خلاصة التحقيق، ثم اضغط «إملاء صوتي» تحت الحقل المطلوب. سجّل كلامك، أوقف التسجيل، ثم حوّله إلى نص وراجعه قبل الإدراج.</p>
          <p className="muted">الحقول المتاحة: الملاحظة، الوقائع، الاستنتاج، المسؤوليات والاقتراحات. الإفادات والأسئلة والأجوبة تُستورد من تفريغ الجلسة المراجع.</p>
          {saved.status === "FINAL" && <p role="status">هذا المحضر صادر. أعد فتحه بإجراء التصحيح قبل إضافة إملاء جديد.</p>}
        </> : <>
          <p role="status">الإملاء الصوتي متاح للمحققين المكلّفين بهذه الجلسة ممن لديهم صلاحية تحرير المحاضر. حسابك الحالي غير مخوّل باستخدامه هنا.</p>
          <p>المحققون المكلّفون: {session.investigators.map(i => i.full_name).join("، ") || "لم يُكلّف محقق بعد"}.</p>
          <p className="muted">استخدم حساب المحقق المكلّف. إدارة النظام وحدها لا تمنح صلاحية الإملاء باسم المحقق.</p>
        </>}
      </div></details>
      {picker && <Modal title="اختيار أصحاب الإفادات" onClose={() => setPicker(false)} size="lg"><p className="report-picker-intro">اختر شخصاً أو أكثر. تُستورد بياناتهم وإفاداتهم والأسئلة والأجوبة المراجعة من هذه الجلسة، دون إعادة كتابة.</p>
        {error && <Alert kind="danger">{error}</Alert>}
        {!people.some(p => p.participant_key) && <p>لا يوجد أشخاص مسجّلون للاختيار. <Link to={`/investigations/${session.id}/edit`}>أضف الأشخاص إلى الجلسة أولاً</Link>.</p>}
        <label className="checkbox"><input type="checkbox" checked={additional} onChange={e => { setAdditional(e.target.checked); setChosen([]); }} />إضافة إفادة أخرى لشخص لديه إفادة محفوظة</label>
        {people.filter(p => p.participant_key).map(p => {
          const exists = document.blocks.some(b => b.type === "statement" && b.participant_key === p.participant_key);
          return <label className="checkbox report-person-choice" key={p.key}><input type="checkbox" disabled={disabled || (exists && !additional)} checked={chosen.includes(p.participant_key!)} onChange={e => setChosen(v => e.target.checked ? [...v, p.participant_key!] : v.filter(k => k !== p.participant_key))} />{p.label} {exists && <span className="muted">— له إفادة</span>}</label>;
        })}<div className="flex gap wrap"><button className="btn btn-primary" disabled={disabled || !chosen.length} onClick={() => void prepare()}>تجهيز الإفادات المحددة ({chosen.length})</button><button className="btn" onClick={() => setPicker(false)}>إلغاء</button></div>
      </Modal>}
      {store.conflict && <section className="card card-body" aria-label="مصالحة تعارض الحفظ"><h2>قارن النسختين واختر لكل قسم</h2>
        <div className="report-compare">{[document, store.conflict.document].map((version, index) => <div key={index}><p>{index ? "المحفوظة" : "نسختي"}: {version.subject}</p><p>الإحالة: <bdi>{version.opening?.referral_number}</bdi> — {version.opening?.referral_date} — {version.opening?.referral_authority}</p><p>تأكيد اليمين: {version.opening?.oath_confirmed ? "نعم" : "لا"} · اللباس العسكري: {version.opening?.uniform_confirmed ? "نعم" : "لا"}</p></div>)}</div>
        <div className="report-compare">{[document, store.conflict.document].map((version, index) => <div key={index}><h3>{index ? "الختام المحفوظ" : "الختام في نسختي"}</h3><p className="preserve-lines">{version.closing?.text || "لم يضف ختام"}</p><p>{version.closing?.location} · <bdi>{version.closing?.date}</bdi></p></div>)}</div>
        <Field label="عنوان المحضر والتكليفات والافتتاح والختام"><select className="select" value={headerChoice} onChange={e => setHeaderChoice(e.target.value as "local" | "server")}><option value="local">بيانات نسختي الحالية</option><option value="server">بيانات النسخة المحفوظة</option></select></Field>
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
      {mode === "document" ? <section className="report-document-editor"><h2>تحرير المحضر قبل الطباعة</h2>
        <p>عدّل النص داخل المساحات المحددة؛ تُحفظ التغييرات في المحضر نفسه. العناوين والعبارات الرسمية وبيانات الأشخاص محمية. راجع PDF بعد إكمال التعديلات للتحقق من توزيع الصفحات.</p>
        {saved.status === "FINAL" && <Alert kind="info">المحضر صادر للقراءة فقط. استخدم إعادة الفتح للتصحيح من شاشة المراجعة لإنشاء نسخة لاحقة.</Alert>}
        {previewError && <Alert kind="danger">تعذر تحديث العرض. تعديلاتك باقية؛ تحقق من الحفظ ثم أعد المحاولة.</Alert>}
        <ReportDocumentEditor html={preview} disabled={disabled || intakeBlocked} onEdit={(block, key, text) => change(v => editReportText(v, block, key, text))} />
      </section> : mode === "review" ? <section className="report-review"><h2>المعاينة النهائية — PDF</h2><p>هذه المعاينة تستخدم محرّك الإصدار نفسه. النسخة غير الصادرة تحمل علامة مسودة.</p>
        <button className="btn" onClick={() => setMode("document")}>تحرير المحضر قبل الطباعة</button>
        {busy && <p role="status">جارٍ إنشاء معاينة PDF…</p>}
        {pdf && <><div className="flex gap wrap"><a className="btn" href={pdf} download={`draft-${session.session_number}.pdf`}>تنزيل المعاينة PDF</a><a className="btn" href={pdf} target="_blank" rel="noopener noreferrer">فتح PDF في نافذة مستقلة</a></div><p className="muted">إذا لم يعرض متصفحك الملف داخل الصفحة، افتحه في نافذة مستقلة أو نزّله.</p><iframe className="report-pdf-frame" src={pdf} title="معاينة PDF النهائية" /></>}
        {!pdf && <button className="btn" disabled={busy} onClick={() => void openPdf()}>إنشاء المعاينة الحالية</button>}
        {issues.length > 0 && <div className="card card-body"><h3>أكمل قبل الإصدار</h3>{issues.map((issue, i) => <button className="btn report-attention" key={`${issue.block}-${issue.field}-${i}`} onClick={() => select(issue.block, issue.field)}>{issue.label} — {issue.block === "opening" ? "افتتاح المحضر" : issue.block === "closing" ? "ختام المحضر" : blockLabel(document.blocks.find(b => b.id === issue.block)!, document.blocks.findIndex(b => b.id === issue.block))}</button>)}</div>}
        <ReportIssuance sessionId={session.id} state={saved} blocked={dirty || busy || saving || !!dictation || !pdf} canApprove={isLead} onState={accept} onStatusChange={onStatusChange} />
      </section> : <>
        <nav className="report-mobile-tabs" aria-label="أجزاء مساحة المحضر">{([['outline', 'الأقسام'], ['edit', 'الكتابة'], ['preview', 'المحضر']] as const).map(([key, label]) => <button className="btn" key={key} aria-pressed={mobilePane === key} onClick={() => setMobilePane(key)}>{label}</button>)}</nav>
        <div className={`report-studio-grid show-${mobilePane} ${showPreview ? "with-preview" : "focus-writing"}`}>
          <aside className="card report-outline" aria-label="أقسام المحضر"><div className="card-head">أقسام المحضر <span>{document.blocks.length}</span></div><div className="card-body">
            <button className="btn report-opening-nav" aria-current={selected === "opening" ? "true" : undefined} onClick={() => select("opening")}>افتتاح المحضر <span className={issues.some(i => i.block === "opening") ? "report-needs" : "muted"}>{issues.some(i => i.block === "opening") ? "يحتاج استكمالاً" : "الحقول مكتملة"}</span></button>
            {!document.blocks.length && <p>ابدأ باختيار أصحاب الإفادات، ثم أضف الملاحظات والخلاصة.</p>}
            {document.blocks.map((block, index) => <div className={`report-outline-item ${selected === block.id ? "selected" : ""}`} key={block.id}>
              <button className="btn btn-ghost" aria-current={selected === block.id ? "true" : undefined} onClick={() => select(block.id)}>{blockLabel(block, index)}{attention(block).length > 0 && <span className="report-needs">يحتاج استكمالاً</span>}</button>
              <details className="report-section-actions"><summary>ترتيب القسم أو إزالته</summary><div className="flex gap"><button className="btn btn-sm" aria-label={`نقل ${blockLabel(block, index)} لأعلى`} disabled={disabled || index === 0} onClick={() => move(block.id, -1)}>↑</button><button className="btn btn-sm" aria-label={`نقل ${blockLabel(block, index)} لأسفل`} disabled={disabled || index === document.blocks.length - 1} onClick={() => move(block.id, 1)}>↓</button>
                <button className="btn btn-sm" disabled={disabled} onClick={() => { setRemoved({ block, index }); change(v => ({ ...v, blocks: v.blocks.filter(b => b.id !== block.id) })); setSelected(document.blocks[index + 1]?.id ?? document.blocks[index - 1]?.id ?? "opening"); }}>إزالة</button></div></details>
            </div>)}{!document.blocks.some(b => b.type === "conclusion") && <button className="btn report-attention" disabled={disabled || intakeBlocked} onClick={() => addConclusion()}>أضف خلاصة التحقيق</button>}
            {document.closing && <button className="btn" aria-current={selected === "closing" ? "true" : undefined} onClick={() => select("closing")}>ختام المحضر والتوقيعات</button>}
            <div className="report-outline-help"><strong>خطوة بخطوة</strong><p>أكمل الافتتاح، أضف الإفادات والملاحظات، ثم اكتب الخلاصة وراجع النسخة النهائية.</p></div>
          </div></aside>
          <section className="card report-edit-panel"><div className="card-head"><div><small className="report-eyebrow">مساحة التحرير</small>{selected === "opening" ? "افتتاح المحضر" : selected === "closing" ? "ختام المحضر" : active ? blockLabel(active, document.blocks.indexOf(active)) : "الكتابة"}</div><span className="report-state-badge">{saved.status === "FINAL" ? "للقراءة" : "يحفظ تلقائياً"}</span></div><div className="card-body">
            {issues.some(i => i.block === selected) && <div className="report-inline-checklist"><span>لإكمال هذا القسم</span><div>{issues.filter(i => i.block === selected).map(issue => <button className="btn btn-sm" key={issue.field} onClick={() => select(issue.block, issue.field)}>{issue.label}</button>)}</div></div>}
            {selected === "closing" && document.closing ? <>
              <p>يظهر هذا الختام بعد جميع الأقسام مع توقيع الكاتب والمحقق. راجع الصياغة والتاريخ قبل الإصدار؛ الصورة المرجعية لا تُدرج كتوقيع.</p>
              <Field label="نص ختام المحضر" full><textarea id="report-field-closing-text" className="textarea" rows={7} maxLength={10000} disabled={disabled} value={document.closing.text} onChange={e => change(v => ({ ...v, closing: { ...v.closing!, text: e.target.value } }))} /></Field>
              <Field label="مكان ختام المحضر"><input id="report-field-closing-location" className="input" maxLength={500} disabled={disabled} value={document.closing.location} onChange={e => change(v => ({ ...v, closing: { ...v.closing!, location: e.target.value } }))} /></Field>
              <Field label="تاريخ ختام المحضر"><input id="report-field-closing-date" className="input" type="date" disabled={disabled} value={document.closing.date ?? ""} onChange={e => change(v => ({ ...v, closing: { ...v.closing!, date: e.target.value || null } }))} /></Field>
            </> : selected === "opening" ? <ReportOpeningEditor document={document} session={session} disabled={disabled} onChange={value => change(() => value)} /> : active ? <ReportSectionEditor key={active.id} block={active} blocks={document.blocks} session={session} catalogue={catalogue} templates={templates} disabled={disabled} canManage={can("reports.templates.manage")} voiceAllowed={voiceAllowed}
              onChange={replace} onTemplate={t => setTemplates(v => [...v, t])} onVoice={target => { if (!dictation) setDictation(target); else setError("أكمل التسجيل المفتوح أو أغلقه قبل تغيير حقل الإملاء."); }} onRefresh={() => void compare()} /> : <p className="muted">اختر قسماً من المحضر أو أضف إفادة أو ملاحظة.</p>}
          </div></section>
          <section className="card report-paper"><div className="card-head">المحضر — اضغط القسم لتعديله</div>{previewError && <p role="status">تعذر تحديث المعاينة؛ آخر معاينة ناجحة باقية.</p>}
            <iframe ref={frame} title="محضر التحقيق — اضغط للتعديل" srcDoc={preview} onLoad={frameLoaded} sandbox="allow-same-origin allow-modals" /></section>
        </div>
      </>}
      {voiceAllowed && <ReportDictation sessionId={session.id} target={dictation} disabled={disabled} flush={flush} onState={accept} onClose={() => setDictation(null)} onBusy={setBusy} />}
    </>}
  </div>;
}
