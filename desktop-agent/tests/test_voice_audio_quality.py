from types import SimpleNamespace
from app.ai.speaker_id_service import clean_speaker_spans, clean_diarized_speaker_spans
from app.ai.types import SpeechRegion


def segment(label, start, end, overlap=False):
    return SimpleNamespace(speaker_label=label, start_seconds=start, end_seconds=end, is_overlap=overlap)


def test_removes_flagged_and_unflagged_overlap_and_duplicate_windows():
    spans = clean_speaker_spans([
        segment('A', 0, 10), segment('A', 0, 5),
        segment('B', 3, 6), segment('A', 8, 9, True),
    ])
    assert spans['A'] == [(0, 3), (6, 8), (9, 10)]
    assert spans['B'] == []


def test_preserves_clean_turns():
    assert clean_speaker_spans([segment('A', 0, 3), segment('B', 3, 6)]) == {
        'A': [(0, 3)], 'B': [(3, 6)]}


def test_recovers_clean_speech_in_live_partial_overlap_regression():
    turns = [segment('SPEAKER_00', 1.100, 8.560, True),
             segment('SPEAKER_01', 1.280, 2.880, True)]
    assert clean_diarized_speaker_spans(turns, [SpeechRegion(0, 9)]) == {
        'SPEAKER_00': [(1.1, 1.28), (2.88, 8.56)], 'SPEAKER_01': []}
    # Recovering clean intervals must not alter the transcript's overlap flags.
    assert all(turn.is_overlap for turn in turns)


def test_unknown_overlap_remains_excluded_even_inside_duplicate_turn():
    turns = [segment('A', 0, 10), segment('A', 2, 4, True)]
    assert clean_diarized_speaker_spans(turns, [SpeechRegion(0, 10)]) == {
        'A': [(0, 2), (4, 10)]}
    assert clean_diarized_speaker_spans([segment('A', 0, 10, True)], [SpeechRegion(0, 10)]) == {}


def test_voice_spans_use_vad_and_count_overlapping_regions_once():
    turns = [segment('A', 0, 10), segment('B', 4, 6)]
    speech = [SpeechRegion(1, 3), SpeechRegion(2, 5), SpeechRegion(7, 8)]
    assert clean_diarized_speaker_spans(turns, speech) == {
        'A': [(1, 4), (7, 8)], 'B': []}


def test_competitor_outside_vad_still_explains_coarse_overlap_flag():
    turns = [segment('A', 0, 10, True), segment('B', 8, 10, True)]
    assert clean_diarized_speaker_spans(turns, [SpeechRegion(1, 7)]) == {
        'A': [(1, 7)], 'B': []}
