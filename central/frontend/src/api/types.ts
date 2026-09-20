export type SessionStatus = "DRAFT" | "RECORDING" | "PROCESSING" | "COMPLETED" | "FAILED" | "ARCHIVED";
export type JobStatus = "REQUESTED" | "ACCEPTED" | "PROCESSING" | "COMPLETED" | "FAILED" | "CANCELLED";
export type SpeakerRole = "INVESTIGATOR" | "SUBJECT" | "WITNESS" | "OTHER" | "UNKNOWN";
export type AssignmentRole = "LEAD" | "ASSISTANT";
export type AgentState =
  | "CREATED"
  | "RECEIVING_AUDIO"
  | "PREPROCESSING"
  | "DIARIZING"
  | "TRANSCRIBING"
  | "FINALIZING"
  | "SYNCING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export interface Profile {
  identity_id?: string | null;
  id: string;
  user_id: string;
  full_name: string;
  rank: string | null;
  military_id: string | null;
  security_branch: SecurityBranch | null;
  unit: string | null;
  department: string | null;
  job_title: string | null;
  phone: string | null;
  email: string | null;
  location: string | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CurrentUser {
  id: string;
  username: string;
  is_active: boolean;
  must_change_password: boolean;
  roles: string[];
  permissions: string[];
  last_login_at: string | null;
  profile: Profile | null;
}

export interface UserRow {
  id: string;
  username: string;
  is_active: boolean;
  must_change_password: boolean;
  roles: string[];
  last_login_at: string | null;
  created_at: string;
  profile: Profile | null;
}

/** One person on a session, whatever row they came from.
 *
 * `person_name` is the CANONICAL name from the registry and `rank` is separate decoration -
 * folding them together is what made the same human read as "MAJOR ALI" in one section and
 * "ALI" in another. GET /investigations/{id}/people is the only source for these.
 */
export interface SessionPerson {
  identity_id: string | null;
  person_name: string;
  rank: string | null;
  source: "SUBJECT" | "INVESTIGATOR";
  participant_key: string | null;
  selectable: boolean;
  blocked_reason: string | null;
}

/** One runtime-tunable setting, defined entirely by the backend's whitelist. */
export interface ConfigField {
  key: string;
  group: string;
  label: string;
  description: string;
  type: "int" | "float" | "bool" | "select" | "text";
  value: string | number | boolean;
  min: number | null;
  max: number | null;
  options: string[] | null;
}

export interface ConfigOut {
  fields: ConfigField[];
}

export interface InvestigatorBrief {
  identity_id?: string | null;
  id: string;
  full_name: string;
  rank: string | null;
  military_id: string | null;
  /** Null until they are assigned to a session, which is when they are registered as a person. */
  security_branch: SecurityBranch | null;
  unit: string | null;
  department: string | null;
  job_title: string | null;
  assignment_role: AssignmentRole | null;
}

export type PersonType = "MILITARY" | "CIVILIAN" | "UNKNOWN";
export type SecurityBranch = "ARMY" | "ISF" | "GENERAL_SECURITY" | "STATE_SECURITY" | "CUSTOMS" | "OTHER";
export type IdentityConfidence = "DECLARED" | "DOCUMENT_SEEN" | "VERIFIED";
export type UndocumentedReason = "NO_DOCUMENTS" | "REFUSED" | "UNIDENTIFIED" | "DOCUMENTS_WITHHELD" | "OTHER";
export type SubjectDocumentType =
  | "NATIONAL_ID"
  | "CIVIL_EXTRACT"
  | "PASSPORT"
  | "RESIDENCY_PERMIT"
  | "UNHCR_CARD"
  | "UNRWA_CARD"
  | "REFUGEE_TRAVEL_DOC"
  | "MILITARY_ID"
  | "DRIVING_LICENSE"
  | "OTHER";

export interface SubjectDocument {
  id?: string;
  subject_id?: string;
  document_type: SubjectDocumentType;
  document_number: string | null;
  issuing_country: string | null;
  issue_date: string | null;
  expiry_date: string | null;
  notes: string | null;
  has_file?: boolean;
  original_filename?: string | null;
  mime_type?: string | null;
  size_bytes?: number | null;
  sha256?: string | null;
  uploaded_by?: string | null;
  uploaded_by_name?: string | null;
  created_at?: string;
  is_expired?: boolean;
}

export interface Subject {
  identity_id?: string | null;
  id?: string;
  /** Stable session-local handle for this participant. Absent on a row the operator has just
      added; the backend mints it and echoes it back. Round-trip it or the server loses track
      of which submitted person is which existing one. NOT a person identifier. */
  participant_key?: string;
  subject_name: string | null;
  person_type: PersonType;
  military_id: string | null;
  rank: string | null;
  unit: string | null;
  department: string | null;
  security_branch: SecurityBranch | null;
  nationality_code: string | null;
  nationality_name: string | null;
  register_number: string | null;
  place_of_registration: string | null;
  /** محل القيد as a recognised code. Only this validated value keys an identity;
      the free-text field above is kept for legacy rows and never derives. */
  caza_code: string | null;
  is_unregistered: boolean;
  is_undocumented: boolean;
  undocumented_reason: UndocumentedReason | null;
  identity_confidence: IdentityConfidence;
  notes: string | null;
  documents: SubjectDocument[];
  duplicate_of_sessions?: string[];
}

export interface Recording {
  id: string;
  session_id: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number | null;
  duration_seconds: number | null;
  sha256: string | null;
  source: "BROWSER_RECORDING" | "FILE_UPLOAD";
  upload_status: "PENDING" | "UPLOADED" | "DISABLED";
  created_at: string;
}

export interface Investigation {
  id: string;
  session_number: string;
  title: string;
  description: string | null;
  location: string | null;
  session_date: string | null;
  start_time: string | null;
  end_time: string | null;
  status: SessionStatus;
  notes: string | null;
  expected_speaker_count: number;
  speaker_limit_warning: boolean;
  created_by: string;
  created_by_name: string | null;
  created_at: string;
  updated_at: string;
  investigators: InvestigatorBrief[];
  subjects: Subject[];
  recordings: Recording[];
  latest_job_status: JobStatus | null;
  has_transcript: boolean;
  duration_seconds: number | null;
}

export interface InvestigationListItem {
  id: string;
  session_number: string;
  title: string;
  location: string | null;
  session_date: string | null;
  status: SessionStatus;
  lead_investigator: string | null;
  duration_seconds: number | null;
  created_at: string;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Dashboard {
  total_sessions: number;
  sessions_today: number;
  processing: number;
  completed: number;
  recent: InvestigationListItem[];
}

export interface ProcessingToken {
  job_id: string;
  recording_id: string;
  session_id: string;
  processing_token: string;
  accept_by: string;
  expires_at: string;
  allowed_action: string;
  speaker_limit_warning: boolean;
}

export interface Job {
  id: string;
  session_id: string;
  recording_id: string;
  status: JobStatus;
  agent_state: AgentState | null;
  failure_stage: string | null;
  error_message: string | null;
  idempotency_key: string | null;
  token_accept_by: string;
  token_expires_at: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  workstation_agent_id: string | null;
}

export interface Segment {
  id: string;
  sequence: number;
  speaker_label: string;
  start_seconds: number;
  end_seconds: number;
  original_text: string;
  edited_text: string | null;
  confidence: number | null;
  is_overlap: boolean;
  edited_by: string | null;
  edited_by_name: string | null;
  edited_at: string | null;
}

export type IdentificationStatus = "NONE" | "SUGGESTED" | "CONFIRMED" | "REJECTED";

export interface Speaker {
  recording_id?: string | null;
  recording_name?: string | null;
  id: string;
  session_id: string;
  speaker_label: string;
  display_name: string | null;
  speaker_role: SpeakerRole;
  notes: string | null;
  segment_count: number;
  total_seconds: number;
  updated_at: string;
  /** Voice-based suggestion. Never applied automatically - a human confirms it. */
  identification_status: IdentificationStatus;
  suggested_name: string | null;
  suggested_score: number | null;
  suggested_model: string | null;
  has_voice_embedding: boolean;
  /** Canonical person this speaker is. Backend-owned; never sent by the client. */
  identity_id: string | null;
  identity_name: string | null;
}

export interface VoiceEnrollment {
  id: string;
  /** Canonical identity this print belongs to. Backend-owned. */
  identity_id: string | null;
  /** CURRENT canonical name/reference, resolved through identity_id. */
  person_name: string;
  /** What was recorded when the print was taken. History, never authoritative. */
  enrolled_person_name: string | null;
  notes: string | null;
  model: string;
  model_revision: string | null;
  provider: string | null;
  embedding_dim: number;
  sample_seconds: number | null;
  source_session_id: string | null;
  source_speaker_label: string | null;
  consent_recorded: boolean;
  is_active: boolean;
  enrolled_by: string | null;
  enrolled_by_name: string | null;
  created_at: string;
  updated_at: string;
}

export type BiometricPrintStatus = "SINGLE_PRINT" | "NEAR_DUPLICATE" | "COHERENT" | "ISOLATED";

/** One print's standing among its own person's other prints. Advisory; never a vector. */
export interface BiometricPrintCheck {
  enrollment_id: string;
  created_at: string;
  source_session_id: string | null;
  source_speaker_label: string | null;
  model: string;
  embedding_dim: number;
  sample_seconds: number | null;
  peer_similarity_max: number | null;
  peer_similarity_min: number | null;
  coherent_peer_count: number;
  /** 1-based within the group. Two components = possibly two different voices. */
  component_id: number;
  status: BiometricPrintStatus;
  updated_at: string;
  review_status: "NONE" | "FLAGGED" | "RESOLVED";
}

export interface BiometricGroup {
  model: string;
  embedding_dim: number;
  model_revision: string | null;
  provider: string | null;
  component_count: number;
  prints: BiometricPrintCheck[];
  pairs: { first_id: string; second_id: string; similarity: number }[];
}

export type VoiceReviewAction = "NOTE" | "FLAG" | "RESOLVE" | "DEACTIVATE";
export interface VoiceReview {
  id: string;
  enrollment_id: string;
  action: VoiceReviewAction;
  reason: string;
  reviewer_name: string | null;
  created_at: string;
}
export interface VoiceSource {
  recording_id: string;
  transcript_id: string;
  segments: { start_seconds: number; end_seconds: number }[];
}

/** Result of the manual فحص البصمات الصوتية. Read-only: the server changes nothing. */
export interface BiometricCheck {
  identity_id: string;
  person_name: string;
  total_active_prints: number;
  number_of_components: number;
  overall_status: "NO_PRINTS" | "SINGLE_PRINT" | "COHERENT" | "REVIEW_REQUIRED";
  coherence_threshold: number;
  near_duplicate_threshold: number;
  groups: BiometricGroup[];
  identity_confirmations: VoiceIdentityConfirmation[];
}

export interface VoiceIdentityConfirmation {
  id: string;
  enrollment_ids: string[];
  reason: string;
  reviewer_name: string | null;
  created_at: string;
  status: "ACTIVE" | "STALE" | "REOPENED";
  reopened_reason: string | null;
  reopened_by_name: string | null;
  reopened_at: string | null;
}

export interface PersonSearchResult {
  identity_id: string;
  person_name: string;
  /** Totals cover only sessions this user may access - never global activity. */
  accessible_session_count: number;
  accessible_print_count: number;
  accessible_sample_seconds: number;
}

export interface EnrollmentCandidate {
  speaker_id: string;
  session_id: string;
  session_number: string;
  session_title: string | null;
  speaker_label: string;
  /** Session-local label. May carry a rank - never send it as a canonical name. */
  display_name: string;
  /** Canonical registry name. The only value enrolment may assert as person_name. */
  person_name: string;
  speaker_role: SpeakerRole;
  identity_id: string;
  sample_seconds: number | null;
  enrollment_state: "never_enrolled" | "enrolled_inactive";
  inactive_enrollment_id: string | null;
  created_at: string;
}

export interface Transcript {
  id: string;
  session_id: string;
  recording_id: string;
  job_id: string;
  status: string;
  language: string;
  stt_provider: string | null;
  stt_model: string | null;
  stt_model_revision: string | null;
  diarization_provider: string | null;
  diarization_model: string | null;
  diarization_model_revision: string | null;
  vad_model: string | null;
  agent_version: string | null;
  processing_device: string | null;
  speaker_count: number | null;
  warnings: string[];
  created_at: string;
  completed_at: string | null;
  audio_available: boolean;
  segments: Segment[];
  speakers: Speaker[];
}

export interface Workstation {
  id: string;
  agent_id: string;
  device_name: string | null;
  agent_version: string | null;
  stt_provider: string | null;
  stt_model: string | null;
  stt_model_revision: string | null;
  diarization_provider: string | null;
  diarization_model: string | null;
  diarization_model_revision: string | null;
  processing_device: string | null;
  gpu_name: string | null;
  status: "ONLINE" | "DEGRADED" | "OFFLINE";
  last_seen_at: string | null;
  registered_by: string | null;
  registered_by_name: string | null;
  created_at: string;
}

export interface AuditEntry {
  id: string;
  user_id: string | null;
  username: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  safe_metadata: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

/* ---- Local AI Agent ---- */
export interface AgentHealth {
  status: string;
  agent_id: string;
  agent_version: string;
  device_name: string;
  uptime_seconds: number;
}

export interface AgentModelStatus {
  name: string;
  provider: string;
  model: string;
  revision: string | null;
  state: "NOT_PROVISIONED" | "PROVISIONED" | "LOADING" | "READY" | "ERROR";
  error: string | null;
  loaded_at: string | null;
}

export interface AgentCapabilities {
  agent_id: string;
  agent_version: string;
  device_name: string;
  processing_device: "cuda" | "cpu";
  cuda_available: boolean;
  gpu_name: string | null;
  stt: AgentModelStatus;
  diarization: AgentModelStatus;
  vad: AgentModelStatus;
  /** Optional on purpose: an agent older than speaker identification omits it entirely, and
      that absence is exactly what the status panel needs to be able to show. */
  speaker_id?: AgentModelStatus;
  max_speakers: number;
  supported_formats: string[];
  max_upload_bytes: number;
  ready: boolean;
  /** Every model is provisioned (files present) so a load can be attempted. */
  loadable: boolean;
  /** A background model load is in progress. */
  loading: boolean;
  busy: boolean;
  central_sync_enabled: boolean;
}

export interface AgentJob {
  job_id: string;
  session_id: string;
  state: AgentState;
  sync_state: "NOT_STARTED" | "WAITING_TO_SYNC" | "SYNCING" | "SYNCED" | "SYNC_FAILED";
  progress: number;
  message: string | null;
  error_code: string | null;
  error_message: string | null;
  failure_stage: string | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  speaker_count: number | null;
  segment_count: number | null;
  warnings: string[];
  sync_attempts: number;
  last_sync_error: string | null;
}

// ---------------------------------------------------------------- محضر تحقيق (report)

export type ReportStatus = "DRAFT" | "FINAL";
export type TranscriptSourceMode = "CORRECTED" | "ORIGINAL";
export type FushaStatus =
  | "NOT_REQUESTED"
  | "AI_SUGGESTED"
  | "HUMAN_EDITED"
  | "APPROVED"
  | "REJECTED";

/** One س/ج exchange as it will be printed, beside the transcript text it came from. */
export interface ReportQABlock {
  id: string;
  sequence: number;
  question_source_text: string | null;
  answer_source_text: string | null;
  report_question_text: string | null;
  report_answer_text: string | null;
  question_speaker_id: string | null;
  answer_speaker_id: string | null;
  question_speaker_name: string | null;
  answer_speaker_name: string | null;
  answer_speaker_resolved: boolean;
  source_segment_ids: string[];
  source_recording_ids: string[];
  start_seconds: number | null;
  end_seconds: number | null;
  included_in_report: boolean;
  exclusion_reason: string | null;
  fusha_status: FushaStatus;
  llm_suggested_question: string | null;
  llm_suggested_answer: string | null;
  edited_at: string | null;
}

export interface ReportRecordingOption {
  id: string;
  index: number;
  original_filename: string;
  duration_seconds: number | null;
  created_at: string;
  has_transcript: boolean;
  selected: boolean;
}

export interface ReportSpeaker {
  id: string;
  speaker_label: string;
  source_label: string | null;
  recording_id: string | null;
  role: string;
  display_name: string | null;
  person_name: string | null;
  resolved: boolean;
  /** Pre-provenance row: which recording it came from was never stored. */
  legacy: boolean;
  report_name: string;
}

export interface ReportStalePin {
  recording_id: string;
  transcript_id: string;
  reason: string;
}

export interface ReportDraft {
  id: string;
  session_id: string;
  status: ReportStatus;
  report_number: string | null;
  case_subject: string | null;
  report_date: string | null;
  report_time: string | null;
  location: string | null;
  intro_text: string | null;
  closing_text: string | null;
  transcript_source_mode: TranscriptSourceMode;
  unresolved_ack: boolean;
  updated_at: string;
  qa_blocks: ReportQABlock[];
  recordings: ReportRecordingOption[];
  speakers: ReportSpeaker[];
  /** Transcripts edited since the draft was built. Refresh is always explicit. */
  stale: ReportStalePin[];
  missing_fields: string[];
  unresolved_speaker_labels: string[];
  report_version_count: number;
  /** Whether Fusha assistance can be offered on this server at all. */
  llm: {
    available: boolean;
    provider: string;
    model: string | null;
    fallback_reason: string | null;
  };
}

export interface ReportTemplateVersion {
  id: string;
  version: number;
  original_filename: string | null;
  size_bytes: number | null;
  sha256: string;
  validation_status: "UNVALIDATED" | "VALID" | "INVALID";
  validation_message: string | null;
  /** The bundled stand-in, not an approved official form. */
  is_development: boolean;
  is_active: boolean;
  activated_at: string | null;
  notes: string | null;
  uploaded_by: string | null;
  created_at: string;
  /** Issued reports citing this version - such a version is never deleted. */
  reports_issued: number;
}

export interface ReportTemplateList {
  active: ReportTemplateVersion | null;
  /** False while the active form is the development stand-in or does not validate. */
  production_ready: boolean;
  environment: string;
  versions: ReportTemplateVersion[];
}

export interface GeneratedReport {
  id: string;
  report_version: number;
  report_number: string | null;
  template_version: number | null;
  template_is_development: boolean;
  docx_sha256: string;
  context_sha256: string | null;
  template_sha256: string | null;
  size_bytes: number | null;
  qa_block_count: number | null;
  transcript_source_mode: TranscriptSourceMode | null;
  selected_recording_ids: string[];
  pinned_transcripts: { recording_id: string; transcript_id: string; segments_sha256: string }[];
  generated_by: string | null;
  generated_by_name: string | null;
  created_at: string;
}

export interface ReportArchive {
  reports: GeneratedReport[];
  can_finalize: boolean;
  blocked_reasons: string[];
  missing_fields: string[];
  unresolved_speaker_labels: string[];
  active_template_version: number | null;
  active_template_is_development: boolean;
}

export interface ReportVerification {
  report_id: string;
  ok: boolean;
  docx_ok: boolean;
  context_ok: boolean;
  template_ok: boolean;
  detail: string;
}
