from types import SimpleNamespace
from app.ai.speaker_id_service import clean_speaker_spans


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
