"""Index every foreign key column that had no supporting index.

PostgreSQL indexes the *referenced* side of a foreign key (it is a primary or unique key) but
never the *referencing* side. Without that index every `ON DELETE CASCADE` and `ON DELETE SET
NULL` has to sequentially scan each child table to find the rows it must touch, holding locks
while it does. Deleting one user reaches eight such tables here.

It is invisible on a small database and turns into a lock storm on a large one, which is the
worst way to discover it. Sixteen indexes cost a little write throughput and some disk; the
alternative is a delete that scans the whole audit log.

`transcripts.recording_id` and `local_processing_jobs.recording_id` matter most: they hang off
audio_recordings, which grows with every interview.

Revision ID: d1a7f30b6c94
Revises: b2e94c1f7a06
"""

from __future__ import annotations

from alembic import op

revision = "d1a7f30b6c94"
down_revision = "b2e94c1f7a06"
branch_labels = None
depends_on = None

# (index name, table, column) - every FK column that pg_index showed as unindexed.
INDEXES = [
    ("ix_audio_recordings_created_by", "audio_recordings", "created_by"),
    ("ix_investigator_profiles_created_by", "investigator_profiles", "created_by"),
    ("ix_local_processing_jobs_recording_id", "local_processing_jobs", "recording_id"),
    ("ix_local_processing_jobs_requested_by", "local_processing_jobs", "requested_by"),
    ("ix_local_processing_jobs_workstation_id", "local_processing_jobs", "workstation_id"),
    ("ix_role_permissions_permission_id", "role_permissions", "permission_id"),
    ("ix_session_speakers_decided_by", "session_speakers", "decided_by"),
    ("ix_session_speakers_suggested_enrollment_id", "session_speakers", "suggested_enrollment_id"),
    ("ix_subject_documents_uploaded_by", "subject_documents", "uploaded_by"),
    ("ix_transcript_segments_edited_by", "transcript_segments", "edited_by"),
    ("ix_transcripts_recording_id", "transcripts", "recording_id"),
    ("ix_user_roles_role_id", "user_roles", "role_id"),
    ("ix_users_created_by", "users", "created_by"),
    ("ix_voice_enrollments_enrolled_by", "voice_enrollments", "enrolled_by"),
    ("ix_workstations_registered_by", "workstations", "registered_by"),
]


def upgrade() -> None:
    for name, table, column in INDEXES:
        op.create_index(name, table, [column])


def downgrade() -> None:
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
