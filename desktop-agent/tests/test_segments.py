"""Segment post-processing: merging, splitting, overlap, padding reconciliation."""

from __future__ import annotations

from app.ai.diarization_service import mark_overlaps, parse_nemo_segments, relabel_by_first_appearance
from app.ai.segment_service import SegmentSettings, build_windows, merge, plan_segments, split_long, trim_to_vad
from app.ai.types import SpeakerTurn, SpeechRegion


def turns(*items):
    return [SpeakerTurn(*i) for i in items]


def test_parse_nemo_strings_and_dicts():
    out = parse_nemo_segments(["0.00 2.50 speaker_0", "2.50 4.00 speaker_1", {"start": 4.0, "end": 5.0, "speaker": "speaker_0"}, "bad"])
    assert [(t.speaker_label, t.start_seconds, t.end_seconds) for t in out] == [
        ("SPEAKER_00", 0.0, 2.5),
        ("SPEAKER_01", 2.5, 4.0),
        ("SPEAKER_00", 4.0, 5.0),
    ]


def test_relabel_by_first_appearance():
    out = relabel_by_first_appearance(turns(("SPEAKER_02", 0, 1), ("SPEAKER_00", 1, 2), ("SPEAKER_02", 2, 3)))
    assert [t.speaker_label for t in out] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]


def test_overlap_marking():
    out = mark_overlaps(turns(("SPEAKER_00", 0, 5), ("SPEAKER_01", 4, 8), ("SPEAKER_00", 9, 10)), 0.2)
    assert out[0].is_overlap and out[1].is_overlap and not out[2].is_overlap
    # Tiny overlaps below the threshold are ignored.
    out = mark_overlaps(turns(("SPEAKER_00", 0, 5.1), ("SPEAKER_01", 5.0, 8)), 0.2)
    assert not out[0].is_overlap


def test_merge_same_speaker_short_gap():
    out = merge(turns(("SPEAKER_00", 10.2, 12.1), ("SPEAKER_00", 12.25, 15.4)), gap=0.7, max_seconds=28)
    assert len(out) == 1 and out[0].start_seconds == 10.2 and out[0].end_seconds == 15.4


def test_never_merge_across_other_speaker():
    out = merge(turns(("SPEAKER_00", 0, 2), ("SPEAKER_01", 2.05, 2.4), ("SPEAKER_00", 2.5, 4)), gap=0.7, max_seconds=28)
    assert [t.speaker_label for t in out] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]


def test_merge_respects_max_length():
    out = merge(turns(("SPEAKER_00", 0, 20), ("SPEAKER_00", 20.2, 40)), gap=0.7, max_seconds=28)
    assert len(out) == 2


def test_split_long_at_silence():
    speech = [SpeechRegion(0, 14), SpeechRegion(15.5, 40)]
    out = split_long(turns(("SPEAKER_00", 0, 40)), speech, max_seconds=28)
    assert len(out) == 2
    assert out[0].end_seconds == 14 and out[1].start_seconds == 15.5


def test_split_long_hard_fallback():
    out = split_long(turns(("SPEAKER_00", 0, 60)), [], max_seconds=28)
    assert len(out) == 3 and all(t.duration <= 28.001 for t in out)


def test_trim_to_vad_removes_silence():
    out = trim_to_vad(turns(("SPEAKER_00", 0, 10)), [SpeechRegion(1, 3), SpeechRegion(6, 9)])
    assert [(t.start_seconds, t.end_seconds) for t in out] == [(1, 3), (6, 9)]


def test_padding_never_duplicates_neighbour_audio():
    plans = build_windows(turns(("SPEAKER_00", 1.0, 3.0), ("SPEAKER_01", 3.1, 5.0)), duration=10, padding=0.5)
    assert plans[0].window_start == 0.5
    assert plans[0].window_end == 3.05  # half of the 0.1s gap to the next segment
    assert plans[1].window_start == 3.05  # windows never share audio
    assert plans[1].window_end == 5.5


def test_plan_segments_end_to_end():
    t = turns(("SPEAKER_00", 0, 6), ("SPEAKER_01", 6, 13), ("SPEAKER_00", 13, 21))
    speech = [SpeechRegion(0.2, 5.8), SpeechRegion(6.1, 12.9), SpeechRegion(13.2, 20.9)]
    plans = plan_segments(t, speech, 21, SegmentSettings())
    assert [p.speaker_label for p in plans] == ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"]
    assert plans[0].start_seconds == 0.2 and plans[0].end_seconds == 5.8
    assert plans[1].window_start >= plans[0].window_end - 1e-9
