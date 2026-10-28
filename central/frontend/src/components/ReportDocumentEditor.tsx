import { useEffect, useRef, useState } from "react";
import type { HtmlReportDocument } from "@/lib/html-report";
import type { DictationTarget, ConclusionVoiceAction } from "./ReportDictation";

/** Match the print renderer's prose layout without saving on opening the editor. */
export function flowingReportText(value: string): string {
  return value.replace(/\r\n?/g, "\n").split(/\n\s*\n/)
    .map(paragraph => paragraph.replace(/\s+/g, " ").trim()).join("\n\n");
}

// The same canonical JSON is used by forms, autosave, review and issuance.
export function editReportText(doc: HtmlReportDocument, blockId: string, key: string, text: string): HtmlReportDocument {
  if (blockId === "closing" && key === "closing:text" && doc.closing) {
    return { ...doc, closing: { ...doc.closing, text } };
  }
  const [kind, field] = key.split(":");
  return { ...doc, blocks: doc.blocks.map(block => {
    if (block.id !== blockId) return block;
    if ((kind === "question" || kind === "answer") && block.type === "statement") {
      return { ...block, entries: block.entries.map(entry => entry.id === field ? { ...entry, [kind]: text } : entry) };
    }
    if (kind === "finding" && block.type === "conclusion") {
      return { ...block, findings: block.findings.map(finding => finding.id === field ? { ...finding, text } : finding) };
    }
    if (kind === "value" && ((block.type === "note" && !block.template_id && field === "note_text") ||
      (block.type === "conclusion" && (["facts", "inference"].includes(field) || (field === "proposals" && block.proposal_mode === "TEXT"))))) {
      return { ...block, values: { ...block.values, [field]: text } };
    }
    return block;
  }) };
}

export function ReportDocumentEditor({ html, disabled, onEdit, onVoice, onConclusionVoice }: {
  html: string; disabled: boolean; onEdit: (block: string, key: string, text: string) => void;
  onVoice?: (target: DictationTarget) => void;
  onConclusionVoice?: (action: ConclusionVoiceAction) => void;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [displayed, setDisplayed] = useState(html);
  const [targets, setTargets] = useState<{ key: string; label: string }[]>([]);
  const [loadError, setLoadError] = useState(false);
  const focused = useRef(false);
  const position = useRef({ x: 0, y: 0 });
  const latest = useRef({ html, disabled, onEdit, onVoice, onConclusionVoice }); latest.current = { html, disabled, onEdit, onVoice, onConclusionVoice };
  const refresh = () => {
    const view = frame.current?.contentWindow;
    if (view) position.current = { x: view.scrollX, y: view.scrollY };
    setDisplayed(latest.current.html);
  };
  useEffect(() => { if (!focused.current) refresh(); }, [html]);
  useEffect(() => {
    frame.current?.contentDocument?.querySelectorAll<HTMLTextAreaElement>("textarea").forEach(input => { input.disabled = disabled; });
    frame.current?.contentDocument?.querySelectorAll<HTMLButtonElement>(".document-voice-action").forEach(button => { button.disabled = disabled || !onVoice; });
  }, [disabled, onVoice]);
  const loaded = () => {
    let doc: Document | null | undefined;
    try { doc = frame.current?.contentDocument; } catch { setLoadError(true); return; }
    if (!doc) { setLoadError(true); return; }
    setLoadError(false);
    doc.documentElement.classList.add("document-edit-viewport");
    doc.body.classList.add("document-edit-mode");
    frame.current?.contentWindow?.scrollTo(position.current.x, position.current.y);
    const available: { key: string; label: string }[] = [];
    const voiceButton = (host: HTMLElement, label: string, activate: () => void) => {
      const button = doc!.createElement("button");
      button.type = "button";
      button.className = "document-voice-action";
      button.textContent = label;
      // Editor-only DOM: never inserted into server-rendered HTML or PDF exports.
      Object.assign(button.style, { display: "inline-block", minHeight: "40px", padding: "4px 12px", margin: "4px 0",
        border: "1px solid #56683c", borderRadius: "4px", background: "#eef2e3", color: "#203018", font: "inherit", fontSize: "14px", cursor: "pointer" });
      button.disabled = latest.current.disabled;
      button.addEventListener("click", () => { if (!latest.current.disabled) activate(); });
      host.append(button);
    };
    doc.querySelectorAll<HTMLElement>("[data-edit-key]").forEach(element => {
      const block = element.closest<HTMLElement>("[data-block-id]")?.dataset.blockId;
      if (!block) return;
      // Native textareas preserve text-only paste, IME, undo and keyboard behavior.
      const input = doc.createElement("textarea");
      input.value = flowingReportText(element.dataset.editValue ?? "");
      input.setAttribute("aria-label", element.getAttribute("aria-label") ?? "نص المحضر");
      input.className = "document-inline-input";
      const key = `${block}:${element.dataset.editKey}`;
      input.dataset.editorTarget = key;
      available.push({ key, label: `${available.length + 1}. ${element.getAttribute("aria-label") ?? "نص المحضر"}` });
      input.maxLength = element.dataset.editKey === "closing:text" ? 10000 : element.dataset.editKey?.startsWith("question:") ? 20000 : 40000;
      input.disabled = latest.current.disabled;
      input.rows = 1;
      input.wrap = "soft";
      const resize = () => { input.style.height = "0px"; input.style.height = `${input.scrollHeight + 2}px`; };
      input.addEventListener("focus", () => { focused.current = true; });
      input.addEventListener("blur", () => {
        focused.current = false;
        // Do not replace the frame while moving between fields in the document.
        window.setTimeout(() => { if (!focused.current) refresh(); }, 0);
      });
      input.addEventListener("input", () => {
        resize();
        if (!latest.current.disabled) latest.current.onEdit(block, element.dataset.editKey!, input.value);
      });
      element.replaceChildren(input);
      const editKey = element.dataset.editKey ?? "";
      const voiceField = editKey.startsWith("finding:") ? editKey : editKey.startsWith("value:") &&
        ["note_text", "facts", "inference", "proposals"].includes(editKey.slice(6)) ? editKey.slice(6) : null;
      if (voiceField && latest.current.onVoice) {
        voiceButton(element, "إملاء صوتي — " + (element.getAttribute("aria-label") ?? "النص"), () => {
          latest.current.onVoice?.({ block, field: voiceField, label: element.getAttribute("aria-label") ?? "النص" });
        });
      }
      resize();
    });
    if (latest.current.onConclusionVoice) {
      doc.querySelectorAll<HTMLElement>('.conclusion-block tr[data-field="responsibilities"] .statement-text').forEach(cell => {
        voiceButton(cell, "إملاء مسؤولية جديدة", () => latest.current.onConclusionVoice?.("responsibility"));
      });
      doc.querySelectorAll<HTMLElement>('.conclusion-block tr[data-field="proposals"] .statement-text').forEach(cell => {
        if (!cell.querySelector('[data-edit-key="value:proposals"]')) {
          voiceButton(cell, "إملاء اقتراحات", () => latest.current.onConclusionVoice?.("proposals"));
        }
      });
    }
    setTargets(available);
    void doc.fonts.ready.then(() => doc.querySelectorAll<HTMLTextAreaElement>("textarea").forEach(input => {
      input.style.height = "0px"; input.style.height = `${input.scrollHeight + 2}px`;
    }));
  };
  const jump = (key: string) => {
    const input = Array.from(frame.current?.contentDocument?.querySelectorAll<HTMLTextAreaElement>("textarea") ?? []).find(el => el.dataset.editorTarget === key);
    if (input) { input.scrollIntoView({ block: "center", inline: "nearest" }); input.focus({ preventScroll: true }); }
  };
  return <div className="report-document-scroll-workspace">
    <div className="report-document-navigation" aria-label="التنقل داخل المحضر">
      <span role="status">{!html ? "جارٍ تحميل المحضر…" : disabled ? "المحضر للقراءة فقط حالياً" : `${targets.length} حقول قابلة للتحرير — اضغط داخل المساحات الخضراء للكتابة`}</span>
      <div className="flex gap wrap">
        <button className="btn" disabled={!targets.length || disabled} onClick={() => jump(targets[0].key)}>انتقل إلى أول نص قابل للتحرير</button>
        <select className="select" aria-label="انتقل إلى حقل في المحضر" defaultValue="" disabled={!targets.length} onChange={e => { jump(e.target.value); e.target.value = ""; }}>
          <option value="" disabled>اختر النص الذي تريد تعديله</option>{targets.map(target => <option key={target.key} value={target.key}>{target.label}</option>)}
        </select>
        <button className="btn" onClick={() => frame.current?.contentWindow?.scrollTo({ top: 0 })}>بداية المحضر ↑</button>
        <button className="btn" onClick={() => frame.current?.contentWindow?.scrollTo({ top: frame.current?.contentDocument?.documentElement.scrollHeight ?? 0 })}>نهاية المحضر ↓</button>
      </div>
      <p>يملأ النص السطر تلقائياً قبل الانتقال للسطر التالي. تُوصل الأسطر القصيرة المحفوظة كما في الطباعة؛ اترك سطراً فارغاً للفصل بين فقرتين. الافتتاح والعناوين الرسمية محمية. توزيع صفحات الطباعة يظهر في معاينة PDF.</p>
    </div>
    {loadError && <p role="alert">تعذر فتح مساحة التحرير. استخدم تحديث المحضر أو تابع التعديل من شاشة الكتابة.</p>}
    <iframe ref={frame} className="report-document-frame" title="تحرير نص المحضر مباشرة" srcDoc={displayed}
      sandbox="allow-same-origin" onLoad={loaded} />
  </div>;
}
