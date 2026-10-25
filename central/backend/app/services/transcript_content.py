"""One read-only interpretation of reviewed speech, shared by every downstream consumer."""
from app.models.report import TranscriptSourceMode


def speech_parts(segment, mode=TranscriptSourceMode.CORRECTED):
    if mode != TranscriptSourceMode.ORIGINAL and segment.attribution_parts:
        return segment.attribution_parts
    return [{"speaker_label": segment.speaker_label,
             "start_seconds": float(segment.start_seconds), "end_seconds": float(segment.end_seconds),
             "text": segment.original_text if mode == TranscriptSourceMode.ORIGINAL else
                     (segment.edited_text if segment.edited_text is not None else segment.original_text)}]
