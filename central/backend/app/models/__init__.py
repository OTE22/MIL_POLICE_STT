"""ORM models. Importing this package registers every table on Base.metadata."""

from app.models.audit import AuditLog
from app.models.auth import Permission, Role, RolePermission, User, UserRole
from app.models.enums import (
    AssignmentRole,
    IdentificationStatus,
    IdentityConfidence,
    PersonType,
    SecurityBranch,
    SubjectDocumentType,
    UndocumentedReason,
    AuditAction,
    JobStatus,
    RecordingSource,
    RecordingUploadStatus,
    SessionStatus,
    SpeakerRole,
    TranscriptStatus,
    WorkstationStatus,
)
from app.models.investigation import InvestigationSession, SessionInvestigator, Subject, SubjectDocument
from app.models.investigator import InvestigatorProfile
from app.models.processing import AudioRecording, LocalProcessingJob, Workstation
from app.models.transcript import SessionSpeaker, Transcript, TranscriptSegment
from app.models.voice import VoiceEnrollment

__all__ = [
    "AuditLog",
    "Permission",
    "Role",
    "RolePermission",
    "User",
    "UserRole",
    "AssignmentRole",
    "IdentificationStatus",
    "VoiceEnrollment",
    "AuditAction",
    "JobStatus",
    "RecordingSource",
    "RecordingUploadStatus",
    "SessionStatus",
    "SpeakerRole",
    "TranscriptStatus",
    "WorkstationStatus",
    "InvestigationSession",
    "SessionInvestigator",
    "Subject",
    "SubjectDocument",
    "PersonType",
    "SecurityBranch",
    "IdentityConfidence",
    "UndocumentedReason",
    "SubjectDocumentType",
    "InvestigatorProfile",
    "AudioRecording",
    "LocalProcessingJob",
    "Workstation",
    "SessionSpeaker",
    "Transcript",
    "TranscriptSegment",
]
