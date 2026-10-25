import type { Investigation, ReportQABlock } from "@/api/types";
import reportCss from "./html-report.css?raw";
import fontLicense from "../../public/fonts/IBMPlex-LICENSE.txt?raw";
import latinFontLicense from "../../public/fonts/Inter-LICENSE.txt?raw";

export interface BlockTemplate {
  title: string;
  fields: { key: string; label: string; group: string; multiline?: boolean }[];
  clauses: Record<string, string>;
}
export interface StatementCatalogue extends BlockTemplate {
  revision: "statement-html-1";
  note: BlockTemplate;
}
export interface StatementSource {
  block_id: string;
  answer_speaker_id: string | null;
  question_source_text: string | null;
  answer_source_text: string | null;
  source_segment_ids: string[];
  source_recording_ids: string[];
  start_seconds: number | null;
  end_seconds: number | null;
}
export interface StatementEntry {
  id: string;
  question: string;
  answer: string;
  source_block_ids: string[];
  source_snapshot?: StatementSource[];
}
export interface StatementBlock {
  id: string;
  type: "statement";
  speaker_id: string | null;
  participant_key?: string | null;
  identity_id?: string | null;
  person_snapshot?: { session_id: string; values: Record<string, string> };
  values: Record<string, string>;
  identity_checked: boolean;
  attestation_confirmed: boolean;
  entries: StatementEntry[];
}
export interface NoteBlock {
  id: string;
  type: "note";
  values: Record<string, string>;
  template_id?: string | null;
  template_values?: Record<string, string>;
  template_snapshot?: NoteTemplate;
}
export interface NoteTemplate { id: string; title: string; body: string; fields: string[] }
export interface ReportPersonOption { key: string; label: string; participant_key: string | null; identity_id: string | null; speaker_id: string | null }
export type ReportBlock = StatementBlock | NoteBlock;
export interface HtmlReportDocument {
  session_id?: string;
  revision: "statement-html-1";
  subject: string;
  investigator_id: string | null;
  clerk_id?: string | null;
  blocks: ReportBlock[];
}
export interface HtmlReportState { token: string; document: HtmlReportDocument }

export const newEntry = (): StatementEntry => ({ id: crypto.randomUUID(), question: "", answer: "", source_block_ids: [] });
export const newStatement = (): StatementBlock => ({ id: crypto.randomUUID(), type: "statement", speaker_id: null,
  values: {}, identity_checked: false, attestation_confirmed: false, entries: [newEntry()] });
export const newNote = (): NoteBlock => ({ id: crypto.randomUUID(), type: "note", values: {} });

export function blockLabel(block: ReportBlock, index: number): string {
  return block.type === "statement" ? `إفادة ${index + 1} — ${block.values.statement_name || "شخص جديد"}`
    : `ملاحظة ${index + 1} — ${block.values.note_date || "ملاحظة جديدة"}`;
}

/** Never send client-generated source snapshots; the server resolves and retains those. */
export function editableDocument(document: HtmlReportDocument): HtmlReportDocument {
  return { ...document, blocks: document.blocks.map(block => {
    if (block.type === "note") {
      const { template_snapshot: _snapshot, ...editable } = block;
      return editable;
    }
    const { person_snapshot: _snapshot, ...editable } = block;
    return { ...editable, entries: block.entries.map(entry => ({
      id: entry.id, question: entry.question, answer: entry.answer, source_block_ids: entry.source_block_ids,
    })) };
  }) };
}

export function selectionKey(block: StatementBlock): string {
  return block.participant_key ? `participant:${block.participant_key}` : block.identity_id ? `person:${block.identity_id}`
    : block.speaker_id ? `speaker:${block.speaker_id}` : "";
}

export function selectionPayload(option: Pick<ReportPersonOption, "participant_key" | "identity_id" | "speaker_id">) {
  return option.participant_key ? { participant_key: option.participant_key } : option.identity_id ? { identity_id: option.identity_id } : { speaker_id: option.speaker_id };
}

export function applyNoteTemplate(block: NoteBlock, template: NoteTemplate, values: Record<string, string>): NoteBlock {
  const text = template.body.replace(/\{([^{}]+)\}/g, (_, key: string) => values[key]?.trim() || `[${key}]`);
  return { ...block, template_id: template.id, template_values: values, template_snapshot: template,
    values: { ...block.values, note_text: text } };
}

export function detachNoteTemplate(block: NoteBlock): NoteBlock {
  const { template_id: _id, template_values: _values, template_snapshot: _snapshot, ...plain } = block;
  return plain;
}

export function importAnswers(block: StatementBlock, source: ReportQABlock[]): StatementBlock {
  const imported = new Set(block.entries.flatMap(entry => entry.source_block_ids));
  const entries = source.filter(qa => qa.included_in_report && qa.answer_speaker_id === block.speaker_id && !imported.has(qa.id))
    .map(qa => ({ id: crypto.randomUUID(), question: qa.report_question_text ?? "", answer: qa.report_answer_text ?? "",
      source_block_ids: [qa.id], source_snapshot: [{ block_id: qa.id, answer_speaker_id: qa.answer_speaker_id,
        question_source_text: qa.question_source_text, answer_source_text: qa.answer_source_text,
        source_segment_ids: qa.source_segment_ids, source_recording_ids: qa.source_recording_ids,
        start_seconds: qa.start_seconds, end_seconds: qa.end_seconds }] }));
  return { ...block, entries: [...block.entries.filter(e => e.question || e.answer || e.source_block_ids.length), ...entries] };
}

const escape = (value: string) => value.replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));

export function renderHtmlReport(document: HtmlReportDocument, catalogue: StatementCatalogue,
  session: Pick<Investigation, "session_number" | "title" | "investigators">,
  options: { highlight?: boolean; fontDataUrl?: string; latinFontDataUrl?: string; showSources?: boolean } = {}): string {
  const row = (content: string, marker = "", className = "") => `<tr class="${className}"><td class="margin-marker">${marker}</td><td class="statement-text">${content}</td></tr>`;
  const selected = session.investigators.find(i => i.id === document.investigator_id);
  const clerk = session.investigators.find(i => i.id === document.clerk_id);
  const sections = document.blocks.map((block, index) => {
    const template = block.type === "note" ? catalogue.note : catalogue;
    const labels = Object.fromEntries(template.fields.map(f => [f.key, f.label]));
    const field = (key: string, values: Record<string, string>) => `<span class="variable${values[key]?.trim() ? "" : " missing"}" data-field="${escape(key)}">${escape(values[key]?.trim() || `[${labels[key] || key}]`)}</span>`;
    const clause = (key: string, values: Record<string, string>) => escape(template.clauses[key] || "").replace(/\{([a-z_]+)\}/g, (_, name: string) => field(name, values));
    const values = { ...block.values, clerk_name: block.values.clerk_name?.trim() || (clerk ? [clerk.rank, clerk.full_name].filter(Boolean).join(" ") : ""), investigator_name: block.values.investigator_name?.trim()
      || (selected ? [selected.rank, selected.full_name].filter(Boolean).join(" ") : "") };
    if (block.type === "note") {
      return `<section class="statement-block note-block" data-block-id="${escape(block.id)}" aria-label="ملاحظة ${index + 1}"><table class="statement-table"><colgroup><col class="marker-col"><col></colgroup><tbody>
        ${row(clause("body", values), "ملاحظة:", "note-body")}
        ${row(`<div class="signature-row note-signature-row"><div>كاتب عدلي<br>${field("clerk_name", values)}<div class="signature-space"></div></div><div>${clause("place_date", values)}<div>المحقق: ${field("investigator_name", values)}</div><div class="signature-space"></div></div></div>`, "", "statement-signatures")}
        </tbody></table></section>`;
    }
    const entries = block.entries.length ? block.entries : [{ id: "", question: "", answer: "", source_snapshot: [] }];
    const answers = entries.map(entry => {
      const body = [entry.question ? `<p><b>س:</b> ${escape(entry.question)}</p>` : "",
        entry.answer ? `<p>${entry.question ? "<b>ج:</b> " : ""}${escape(entry.answer)}</p>` : '<p class="missing">[نص الإفادة / الجواب]</p>'].join("");
      const sources = options.showSources ? (entry.source_snapshot || []).map(s => `<small class="source-time">المصدر: ${s.start_seconds?.toFixed(3) ?? "—"}–${s.end_seconds?.toFixed(3) ?? "—"} ثانية</small>`).join("") : "";
      return row(body + sources, "س.ج");
    }).join("");
    return `<section class="statement-block" data-block-id="${escape(block.id)}" aria-label="إفادة ${index + 1}"><table class="statement-table"><colgroup><col class="marker-col"><col></colgroup><tbody>
      ${row(clause("heading", values), "", "statement-heading")}
      ${row(clause("identity", values), "س.ج")}
      ${block.identity_checked ? row(clause("identity_check", values)) : ""}
      ${answers}
      ${block.attestation_confirmed ? row(clause("attestation", values)) : ""}
      ${row(`<div class="signature-row"><div>${field("statement_signature_role", values)}<div class="signature-space"></div></div><div>كاتب عدلي<br>${field("clerk_name", values)}<div class="signature-space"></div></div><div>${clause("place_date", values)}<div>المحقق: ${field("investigator_name", values)}</div><div class="signature-space"></div></div></div>`, "", "statement-signatures")}
      </tbody></table></section>`;
  }).join("");
  const font = [["IBM Plex Sans Arabic", options.fontDataUrl], ["Inter", options.latinFontDataUrl]].map(([family, url]) => url?.startsWith("data:font/") ? `@font-face{font-family:"${family}";src:url("${url.replace(/["<>\s]/g, "")}")}` : "").join("\n");
  return `<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; font-src data:; img-src data:; base-uri 'none'; form-action 'none'">
    <title>مسودة محضر — ${escape(document.subject || session.title)}</title><!-- Embedded font license:\n${(fontLicense + "\n" + latinFontLicense).replace(/-->/g, "—>")}\n--><style>${font}\n${reportCss}</style></head>
    <body class="${options.highlight ? "highlight-fields" : ""}"><main class="report-paper"><header class="report-meta"><div>مسودة محضر</div><h1>${escape(document.subject || session.title)}</h1><p>الجلسة: ${escape(session.session_number)} — ${escape(session.title)}</p><p>المحقق المسؤول: ${selected ? escape([selected.rank, selected.full_name].filter(Boolean).join(" ")) : '<span class="missing">[اختر المحقق]</span>'}</p></header>
    ${sections || '<p class="empty-report">أضف إفادة أو ملاحظة لبدء المحضر.</p>'}</main></body></html>`;
}
