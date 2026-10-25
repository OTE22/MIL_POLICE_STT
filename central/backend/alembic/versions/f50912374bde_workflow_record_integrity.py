"""Validate evidence ranges and enforce recording/job/session ownership in PostgreSQL."""
from alembic import op

revision = "f50912374bde"
down_revision = "e4f801263acd"
branch_labels = None
depends_on = None


def upgrade():
    # Validation deliberately aborts the migration on inconsistent evidence; it never repairs
    # history by moving/deleting records. PostgreSQL transactions leave the prior schema intact.
    op.execute("ALTER TABLE transcript_segments VALIDATE CONSTRAINT ck_segment_time")
    op.execute("ALTER TABLE transcript_segments VALIDATE CONSTRAINT ck_segment_confidence")
    op.create_unique_constraint("uq_recording_session", "audio_recordings", ["id", "session_id"])
    op.create_unique_constraint("uq_job_recording_session", "local_processing_jobs", ["id", "recording_id", "session_id"])
    op.execute("ALTER TABLE local_processing_jobs ADD CONSTRAINT fk_job_recording_session FOREIGN KEY (recording_id,session_id) REFERENCES audio_recordings(id,session_id) NOT VALID")
    op.execute("ALTER TABLE transcripts ADD CONSTRAINT fk_transcript_job_session FOREIGN KEY (job_id,recording_id,session_id) REFERENCES local_processing_jobs(id,recording_id,session_id) NOT VALID")
    op.execute("ALTER TABLE session_speakers ADD CONSTRAINT fk_speaker_recording_session FOREIGN KEY (recording_id,session_id) REFERENCES audio_recordings(id,session_id) NOT VALID")
    for table, name in [("local_processing_jobs", "fk_job_recording_session"),
                        ("transcripts", "fk_transcript_job_session"),
                        ("session_speakers", "fk_speaker_recording_session")]:
        op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")
    op.create_check_constraint("ck_session_time", "investigation_sessions", "start_time IS NULL OR end_time IS NULL OR end_time >= start_time")


def downgrade():
    raise RuntimeError("Use a forward migration for investigation integrity changes")
