import { Link } from "react-router-dom";
import type { Investigation } from "@/api/types";
import { Field } from "@/components/ui";
import { NoteTemplateControls } from "./NoteTemplateControls";
import type { DictationTarget } from "./ReportDictation";
import { blockLabel, documentId, emptyReferences, newEntry, type ReportBlock, type StatementCatalogue,
  type NoteTemplate, type ReportReferences, type ConclusionBlock } from "@/lib/html-report";

export interface ReportAttention { block: string; field: string; label: string }
export function attention(block: ReportBlock): ReportAttention[] {
  const issues: ReportAttention[] = [];
  const need = (field: string, label: string, okay: unknown) => { if (!okay) issues.push({ block: block.id, field, label }); };
  need("closing_date", "تاريخ التنظيم", block.values.closing_date?.trim());
  need("closing_location", "مكان التنظيم", block.values.closing_location?.trim());
  if (block.type === "note") need("note_text", "نص الملاحظة", block.values.note_text?.trim());
  if (block.type === "statement") {
    need("statement_name", "صاحب الإفادة", block.values.statement_name?.trim());
    need("entries", "نص الإفادة", block.entries.length);
    block.entries.forEach(e => need(`answer-${e.id}`, "نص الإفادة / الجواب", e.answer.trim()));
    if (block.identity_checked) need("identity_documents", "الوثائق التي تم التحقق منها", block.values.identity_documents?.trim());
  }
  if (block.type === "conclusion") {
    need("facts", "الوقائع", block.values.facts?.trim()); need("inference", "الاستنتاج", block.values.inference?.trim());
    need("responsibility_mode", "المسؤوليات أو قرار لا يوجد", block.responsibility_mode !== "UNREVIEWED" && (block.responsibility_mode !== "FINDINGS" || block.findings.length));
    need("proposal_mode", "الاقتراحات أو قرار لا يوجد", block.proposal_mode !== "UNREVIEWED");
    if (block.proposal_mode === "TEXT") need("proposals", "نص الاقتراحات", block.values.proposals?.trim());
    block.findings.forEach(f => {
      need(`subject-${f.id}`, "الشخص المعني بالمسؤولية", f.participant_key || f.unidentified_subject.trim());
      need(`finding:${f.id}`, "نتيجة المسؤولية", f.text.trim());
      need(`evidence-${f.id}`, "الدليل الداعم للمسؤولية", f.references.recordings.length || f.references.documents.length || f.references.blocks.length);
    });
  }
  return issues;
}

export function ReportSectionEditor({ block, blocks, session, catalogue, templates, disabled, canManage, voiceAllowed,
  onChange, onTemplate, onVoice, onRefresh }: {
  block: ReportBlock; blocks: ReportBlock[]; session: Investigation; catalogue: StatementCatalogue; templates: NoteTemplate[];
  disabled: boolean; canManage: boolean; voiceAllowed: boolean; onChange: (block: ReportBlock) => void;
  onTemplate: (template: NoteTemplate) => void; onVoice: (target: DictationTarget) => void; onRefresh: () => void;
}) {
  const fieldId = (key: string) => `report-field-${block.id}-${key}`;
  const set = (key: string, value: string) => onChange({ ...block, values: { ...block.values, [key]: value } });
  const voice = (key: string, label: string) => voiceAllowed && <button type="button" className="btn btn-sm" disabled={disabled}
    onClick={() => onVoice({ block: block.id, field: key, label })}>إملاء صوتي — {label}</button>;
  const text = (key: string, label: string, rows = 6) => <Field key={key} label={label} full>
    <textarea id={fieldId(key)} className="textarea" aria-label={label} rows={rows} maxLength={40000} disabled={disabled}
      value={block.values[key] ?? ""} onChange={e => set(key, e.target.value)} />
    {voice(key, label)}
  </Field>;
  const references = (refs: ReportReferences, changed: (refs: ReportReferences) => void, id = "references") => <details className="html-field-group" id={fieldId(id)}>
    <summary>ربط الأشخاص والأدلة ({Object.values(refs).flat().length})</summary>
    {([
      ["participants", "الأشخاص", session.subjects.filter(p => p.participant_key).map(p => ({ id: p.participant_key!, label: p.identity_name || p.subject_name }))],
      ["recordings", "التسجيلات", session.recordings.map(r => ({ id: r.id, label: r.original_filename }))],
      ["documents", "الوثائق", session.subjects.flatMap(p => p.documents.filter(d => d.id).map(d => ({ id: d.id!, label: `${p.subject_name} — ${d.document_number || d.original_filename || "وثيقة هوية"}` })))],
      ["blocks", "أقسام المحضر", blocks.filter(b => b.id !== block.id).map((b, i) => ({ id: b.id, label: blockLabel(b, i) }))],
    ] as [keyof ReportReferences, string, { id: string; label: string }[]][]).map(([key, label, options]) => <fieldset key={key} className="report-reference-group"><legend>{label}</legend>
      {!options.length && <span className="muted">لا يوجد مصدر متاح</span>}{options.map(option => <label className="checkbox" key={option.id}>
        <input type="checkbox" disabled={disabled} checked={refs[key].includes(option.id)} onChange={e => changed({ ...refs,
          [key]: e.target.checked ? [...refs[key], option.id] : refs[key].filter(v => v !== option.id) })} /><bdi>{option.label}</bdi></label>)}</fieldset>)}
  </details>;
  const conclusion = block.type === "conclusion" ? block : null;
  const updateConclusion = (patch: Partial<ConclusionBlock>) => conclusion && onChange({ ...conclusion, ...patch });
  const fields = block.type === "statement" ? catalogue.fields : catalogue.note.fields;
  return <div className="report-focused-fields">
    {block.type === "statement" && <>
      <h3>{block.values.statement_name || "إفادة"}</h3>
      <p className="muted">بيانات الشخص مأخوذة من الجلسة. <Link to={`/investigations/${session.id}/edit#participant-${block.participant_key}-father_name`}>تعديل بيانات الشخص</Link></p>
      <button className="btn" disabled={disabled || !block.participant_key} onClick={onRefresh}>مقارنة الإفادة بالمصدر المراجع</button>
      <div id={fieldId("entries")} tabIndex={-1}>
        {block.entries.map((entry, i) => <section className="html-answer-editor" key={entry.id}>
          <h4>الفقرة {i + 1}</h4>
          <details open={!!entry.question}><summary>السؤال (اختياري)</summary><textarea className="textarea" aria-label={`السؤال ${i + 1}`} rows={3} maxLength={20000}
            disabled={disabled} value={entry.question} onChange={e => onChange({ ...block, entries: block.entries.map(v => v.id === entry.id ? { ...v, question: e.target.value } : v) })} /></details>
          <Field label="الجواب / نص الإفادة"><textarea id={fieldId(`answer-${entry.id}`)} className="textarea" aria-label={`نص الإفادة ${i + 1}`} rows={7} maxLength={40000}
            disabled={disabled} value={entry.answer} onChange={e => onChange({ ...block, entries: block.entries.map(v => v.id === entry.id ? { ...v, answer: e.target.value } : v) })} /></Field>
          {!!entry.source_block_ids.length && <details><summary>مصدر النص في هذه الجلسة</summary>{entry.source_snapshot?.map(s => <p key={s.block_id}>
            التسجيل {s.source_recording_ids.map(id => session.recordings.findIndex(r => r.id === id) + 1).join("، ")} · <bdi>{s.start_seconds?.toFixed(2)}–{s.end_seconds?.toFixed(2)}</bdi> ثانية
          </p>)}</details>}
          <button className="btn btn-sm" disabled={disabled} onClick={() => {
            if ((!entry.answer && !entry.question) || window.confirm("إزالة هذه الفقرة من المسودة؟")) onChange({ ...block, entries: block.entries.filter(v => v.id !== entry.id) });
          }}>إزالة الفقرة</button>
        </section>)}
      </div>
      <button className="btn" disabled={disabled} onClick={() => onChange({ ...block, entries: [...block.entries, newEntry()] })}>إضافة سؤال / جواب</button>
    </>}
    {block.type === "note" && <>
      <h3>نص الملاحظة</h3>
      {block.template_id ? <p>صياغة نموذجية؛ عدّل متغيراتها أدناه أو حوّلها إلى نص حر.</p> : text("note_text", "الملاحظة", 10)}
      <details><summary>صياغات جاهزة (اختياري)</summary><NoteTemplateControls block={block} templates={templates} disabled={disabled} canManage={canManage} onChange={onChange} onCreated={onTemplate} /></details>
      {references(block.references ?? emptyReferences(), refs => onChange({ ...block, references: refs }))}
    </>}
    {conclusion && <>
      <h3>خلاصة التحقيق</h3><p className="muted">خلاصة موحدة يساهم فيها محققو الجلسة ويعتمدها المحقق الرئيسي.</p>
      {text("facts", "الوقائع")}{text("inference", "الاستنتاج")}
      <Field label="المسؤوليات"><select id={fieldId("responsibility_mode")} className="select" disabled={disabled} value={conclusion.responsibility_mode} onChange={e => {
        const mode = e.target.value as ConclusionBlock["responsibility_mode"];
        if (mode === "NONE" && conclusion.findings.length && !window.confirm("اختيار لا يوجد سيزيل النتائج من هذه المسودة. هل أكملت مراجعتها؟")) return;
        updateConclusion({ responsibility_mode: mode, findings: mode === "NONE" ? [] : conclusion.findings });
      }}><option value="UNREVIEWED">اختر بعد المراجعة</option><option value="FINDINGS">توجد نتائج مسؤولية</option><option value="NONE">لا يوجد — بعد المراجعة</option></select></Field>
      {conclusion.responsibility_mode === "FINDINGS" && <>
        {conclusion.findings.map((finding, i) => {
          const update = (patch: Partial<typeof finding>) => updateConclusion({ findings: conclusion.findings.map(f => f.id === finding.id ? { ...f, ...patch } : f) });
          return <section className="html-answer-editor" key={finding.id}><h4>نتيجة المسؤولية {i + 1}</h4>
            <Field label="الشخص المعني"><select id={fieldId(`subject-${finding.id}`)} className="select" disabled={disabled} value={finding.participant_key ?? ""} onChange={e => update({ participant_key: e.target.value || null, unidentified_subject: "" })}>
              <option value="">شخص غير محدد الهوية</option>{session.subjects.map(p => <option key={p.participant_key} value={p.participant_key}>{p.identity_name || p.subject_name}</option>)}</select></Field>
            {!finding.participant_key && <Field label="وصف الشخص غير المحدد"><input className="input" disabled={disabled} value={finding.unidentified_subject} onChange={e => update({ unidentified_subject: e.target.value })} /></Field>}
            <Field label="نتيجة المسؤولية"><textarea id={fieldId(`finding:${finding.id}`)} className="textarea" rows={5} maxLength={40000} disabled={disabled} value={finding.text} onChange={e => update({ text: e.target.value })} />{voice(`finding:${finding.id}`, `المسؤولية ${i + 1}`)}</Field>
            {references(finding.references, refs => update({ references: refs }), `evidence-${finding.id}`)}
            <button className="btn btn-sm" disabled={disabled} onClick={() => { if (!finding.text || window.confirm("إزالة نتيجة المسؤولية؟")) updateConclusion({ findings: conclusion.findings.filter(f => f.id !== finding.id) }); }}>إزالة النتيجة</button>
          </section>;
        })}
        <button className="btn" disabled={disabled} onClick={() => updateConclusion({ findings: [...conclusion.findings, { id: documentId(), participant_key: null, unidentified_subject: "", text: "", references: emptyReferences() }] })}>إضافة نتيجة مسؤولية</button>
      </>}
      <Field label="الاقتراحات"><select id={fieldId("proposal_mode")} className="select" disabled={disabled} value={conclusion.proposal_mode} onChange={e => {
        const mode = e.target.value as ConclusionBlock["proposal_mode"];
        if (mode === "NONE" && conclusion.values.proposals && !window.confirm("اختيار لا يوجد سيزيل نص الاقتراحات من المسودة. هل أكملت مراجعته؟")) return;
        updateConclusion({ proposal_mode: mode, values: { ...conclusion.values, proposals: mode === "NONE" ? "" : conclusion.values.proposals ?? "" } });
      }}><option value="UNREVIEWED">اختر بعد المراجعة</option><option value="TEXT">إضافة اقتراحات</option><option value="NONE">لا يوجد — بعد المراجعة</option></select></Field>
      {conclusion.proposal_mode === "TEXT" && text("proposals", "نص الاقتراحات")}
      {references(conclusion.references, refs => updateConclusion({ references: refs }))}
    </>}
    <details className="html-field-group"><summary>{block.type === "statement" ? "الهوية والتوقيع والعبارات المثبتة" : "التاريخ والتوقيع"}</summary>
      <p className="muted">أكمل التحقق والتصديق بعد حصولهما فعلياً. عبارات النموذج الرسمية ثابتة.</p>
      <div className="form-grid">{(conclusion ? catalogue.note.fields.filter(f => f.key.startsWith("closing_") || f.key.endsWith("_name")) : fields.filter(f => f.key !== "note_text")).map(f => <Field label={f.label} key={f.key} full={f.multiline}>
        <input id={fieldId(f.key)} className="input" aria-label={f.label} disabled={disabled} value={block.values[f.key] ?? ""} maxLength={10000} onChange={e => set(f.key, e.target.value)} />
      </Field>)}</div>
      {block.type === "statement" && <>
        <label className="checkbox"><input type="checkbox" disabled={disabled} checked={block.identity_checked} onChange={e => onChange({ ...block, identity_checked: e.target.checked })} />جرى التحقق من وثائق الهوية وإعادتها</label>
        <p>{catalogue.clauses.identity_check}</p>
        <label className="checkbox"><input type="checkbox" disabled={disabled} checked={block.attestation_confirmed} onChange={e => onChange({ ...block, attestation_confirmed: e.target.checked })} />جرت تلاوة الإفادة وتصديقها والتوقيع عليها بحضور الكاتب العدلي</label>
        <p>{catalogue.clauses.attestation}</p>
      </>}
    </details>
    {block.authorship && <p className="muted">آخر تعديل: <bdi>{new Date(block.authorship.updated_at).toLocaleString("ar-LB")}</bdi> — محفوظ في سجل التدقيق</p>}
  </div>;
}
