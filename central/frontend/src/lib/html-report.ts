
export interface BlockTemplate {
  title: string;
  fields: { key: string; label: string; group: string; multiline?: boolean }[];
  clauses: Record<string, string>;
}
export interface StatementCatalogue extends BlockTemplate {
  revision: "statement-html-1" | "investigation-html-2";
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
interface BlockProvenance { authorship?: { created_by?: string; updated_by: string; updated_at: string }; dictation_sources?: string[] }
export interface StatementBlock extends BlockProvenance {
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
export interface NoteBlock extends BlockProvenance {
  id: string;
  type: "note";
  values: Record<string, string>;
  template_id?: string | null;
  template_values?: Record<string, string>;
  template_snapshot?: NoteTemplate;
  references?: ReportReferences;
}
export interface ReportReferences { participants: string[]; recordings: string[]; documents: string[]; blocks: string[] }
export interface ResponsibilityFinding { id: string; participant_key: string | null; unidentified_subject: string; text: string; references: ReportReferences; subject_snapshot?: string }
export interface ConclusionBlock extends BlockProvenance {
  id: string; type: "conclusion"; values: Record<string, string>;
  responsibility_mode: "UNREVIEWED" | "FINDINGS" | "NONE";
  proposal_mode: "UNREVIEWED" | "TEXT" | "NONE";
  findings: ResponsibilityFinding[]; references: ReportReferences;
}
export interface NoteTemplate { id: string; title: string; body: string; fields: string[] }
export interface ReportPersonOption { key: string; label: string; participant_key: string | null; identity_id: string | null; speaker_id: string | null }
export type ReportBlock = StatementBlock | NoteBlock | ConclusionBlock;
export interface HtmlReportDocument {
  session_id?: string;
  revision: "statement-html-1" | "investigation-html-2";
  subject: string;
  investigator_id: string | null;
  clerk_id?: string | null;
  blocks: ReportBlock[];
}
export interface HtmlReportState {
  source_changes: { field: string; before: unknown; after: unknown }[]; token: string; document: HtmlReportDocument; status: "DRAFT" | "FINAL"; source_token: string; sources_changed: boolean; reviewed: boolean; blocked_reasons: string[] }

export function documentId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  // getRandomValues is available on local HTTP origins where randomUUID is not.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

export const newEntry = (): StatementEntry => ({ id: documentId(), question: "", answer: "", source_block_ids: [] });
export const newStatement = (): StatementBlock => ({ id: documentId(), type: "statement", speaker_id: null,
  values: {}, identity_checked: false, attestation_confirmed: false, entries: [newEntry()] });
export const newNote = (): NoteBlock => ({ id: documentId(), type: "note", values: {} });
export const emptyReferences = (): ReportReferences => ({ participants: [], recordings: [], documents: [], blocks: [] });
export const newConclusion = (): ConclusionBlock => ({ id: documentId(), type: "conclusion", values: {}, responsibility_mode: "UNREVIEWED", proposal_mode: "UNREVIEWED", findings: [], references: emptyReferences() });

export function blockLabel(block: ReportBlock, index: number): string {
  if (block.type === "conclusion") return "خلاصة التحقيق";
  return block.type === "statement" ? `إفادة ${index + 1} — ${block.values.statement_name || "شخص جديد"}`
    : `ملاحظة ${index + 1} — ${block.values.note_text?.slice(0, 70) || "ملاحظة جديدة"}`;
}

/** Never send client-generated source snapshots; the server resolves and retains those. */
export function editableDocument(document: HtmlReportDocument): HtmlReportDocument {
  return { ...document, blocks: document.blocks.map(block => {
    const { authorship: _author, dictation_sources: _voice, ...content } = block;
    if (content.type === "conclusion") return { ...content, findings: content.findings.map(({ subject_snapshot: _subject, ...finding }) => finding) };
    if (content.type === "note") {
      const { template_snapshot: _snapshot, ...editable } = content;
      return editable;
    }
    const { person_snapshot: _snapshot, ...editable } = content;
    return { ...editable, entries: content.entries.map(entry => ({
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

