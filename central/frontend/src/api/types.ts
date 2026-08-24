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
  id: string;
  user_id: string;
  full_name: string;
  rank: string | null;
  military_id: string | null;
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

export interface InvestigatorBrief {
  id: string;
  full_name: string;
  rank: string | null;
  military_id: string | null;
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
  id?: string;
  subject_name: string | null;
  reference_number: string | null;
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

export interface Speaker {
  id: string;
  session_id: string;
  speaker_label: string;
  display_name: string | null;
  speaker_role: SpeakerRole;
  reference_number: string | null;
  notes: string | null;
  segment_count: number;
  total_seconds: number;
  updated_at: string;
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
