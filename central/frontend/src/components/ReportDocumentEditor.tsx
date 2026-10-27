import { useEffect, useRef, useState } from "react";
import type { HtmlReportDocument } from "@/lib/html-report";

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

export function ReportDocumentEditor({ html, disabled, onEdit }: {
  html: string; disabled: boolean; onEdit: (block: string, key: string, text: string) => void;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [displayed, setDisplayed] = useState(html);
  const focused = useRef(false);
  const position = useRef(0);
  const latest = useRef({ html, disabled, onEdit }); latest.current = { html, disabled, onEdit };
  const refresh = () => {
    position.current = frame.current?.contentWindow?.scrollY ?? position.current;
    setDisplayed(latest.current.html);
  };
  useEffect(() => { if (!focused.current) refresh(); }, [html]);
  useEffect(() => {
    frame.current?.contentDocument?.querySelectorAll<HTMLTextAreaElement>("textarea").forEach(input => { input.disabled = disabled; });
  }, [disabled]);
  const loaded = () => {
    const doc = frame.current?.contentDocument;
    if (!doc) return;
    frame.current?.contentWindow?.scrollTo(0, position.current);
    doc.querySelectorAll<HTMLElement>("[data-edit-key]").forEach(element => {
      const block = element.closest<HTMLElement>("[data-block-id]")?.dataset.blockId;
      if (!block) return;
      // Native textareas preserve text-only paste, IME, undo and keyboard behavior.
      const input = doc.createElement("textarea");
      input.value = element.dataset.editValue ?? "";
      input.setAttribute("aria-label", element.getAttribute("aria-label") ?? "نص المحضر");
      input.className = "document-inline-input";
      input.maxLength = element.dataset.editKey === "closing:text" ? 10000 : element.dataset.editKey?.startsWith("question:") ? 20000 : 40000;
      input.disabled = latest.current.disabled;
      input.rows = 1;
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
      resize();
    });
    void doc.fonts.ready.then(() => doc.querySelectorAll<HTMLTextAreaElement>("textarea").forEach(input => {
      input.style.height = "0px"; input.style.height = `${input.scrollHeight + 2}px`;
    }));
  };
  return <iframe ref={frame} className="report-document-frame" title="تحرير نص المحضر مباشرة" srcDoc={displayed}
    sandbox="allow-same-origin" onLoad={loaded} />;
}
