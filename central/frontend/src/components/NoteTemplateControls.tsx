import { useState } from "react";
import { http } from "@/api/client";
import { Alert, Field } from "@/components/ui";
import { applyNoteTemplate, detachNoteTemplate, type NoteBlock, type NoteTemplate } from "@/lib/html-report";

export function NoteTemplateControls({ block, templates, disabled, canManage, onChange, onCreated }: {
  block: NoteBlock; templates: NoteTemplate[]; disabled: boolean; canManage: boolean;
  onChange: (block: NoteBlock) => void; onCreated: (template: NoteTemplate) => void;
}) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const template = block.template_snapshot || templates.find(t => t.id === block.template_id);
  return <div className="html-field-group">
    <Field label="صياغة الملاحظة"><select className="select" disabled={disabled} value={block.template_id || ""} onChange={e => {
      const selected = templates.find(t => t.id === e.target.value);
      if (selected && block.values.note_text && !window.confirm("استبدال نص هذه الملاحظة بصياغة القالب المختار؟")) return;
      onChange(selected ? applyNoteTemplate(block, selected, {}) : detachNoteTemplate(block));
    }}><option value="">ملاحظة عامة — نص حر</option>{templates.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}</select></Field>
    {template && <><p className="small muted">املأ الحقول لتكوين النص تلقائياً. لتحرير الفقرة كاملة اختر «تحرير النص بحرية».</p>
      <div className="form-grid">{template.fields.map(key => <Field key={key} label={key} full>
        <textarea className="textarea" rows={2} maxLength={4000} disabled={disabled} value={block.template_values?.[key] || ""}
          onChange={e => onChange(applyNoteTemplate(block, template, { ...block.template_values, [key]: e.target.value }))} />
      </Field>)}</div>
      <button type="button" className="btn btn-sm" disabled={disabled} onClick={() => onChange(detachNoteTemplate(block))}>تحرير النص بحرية</button>
    </>}
    {canManage && <details className="mt-16"><summary>إضافة صياغة قابلة لإعادة الاستخدام</summary>
      <p className="small muted">اكتب صياغة عامة واستخدم {'{اسم الحقل}'} للأجزاء المتغيرة. تُشارك الصياغة فقط بين الجلسات؛ قيم كل ملاحظة تُحفظ داخل محضرها.</p>
      {message && <Alert kind="info">{message}</Alert>}
      <Field label="اسم القالب"><input className="input" maxLength={150} value={title} disabled={busy || disabled} onChange={e => setTitle(e.target.value)} /></Field>
      <Field label="الصياغة والحقول المتغيرة"><textarea className="textarea" rows={5} maxLength={10000} value={body} disabled={busy || disabled}
        placeholder="بعد مراجعة {الجهة} تقرر {الإجراء}." onChange={e => setBody(e.target.value)} /></Field>
      <button type="button" className="btn btn-sm" disabled={busy || disabled || !title.trim() || !body.trim()} onClick={() => {
        setBusy(true); setMessage("");
        void http.post<NoteTemplate>("/report-forms/note-templates", { title, body }).then(result => {
          onCreated(result); setTitle(""); setBody(""); setMessage("حُفظ القالب. يمكنك اختياره من قائمة صياغة الملاحظة.");
        }).catch(() => setMessage("تعذر حفظ القالب. استخدم أقواساً متوازنة مثل {الجهة} وبحد أقصى ٢٠ حقلاً."))
          .finally(() => setBusy(false));
      }}>حفظ كقالب جديد</button>
    </details>}
  </div>;
}
