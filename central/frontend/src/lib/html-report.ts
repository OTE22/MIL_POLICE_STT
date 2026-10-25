
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
export interface HtmlReportState {
  source_changes: { field: string; before: unknown; after: unknown }[]; token: string; document: HtmlReportDocument; status: "DRAFT" | "FINAL"; source_token: string; sources_changed: boolean; reviewed: boolean; blocked_reasons: string[] }

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

