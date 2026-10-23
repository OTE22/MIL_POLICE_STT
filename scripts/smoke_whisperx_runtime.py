"""Exercise real WhisperX CTC alignment with deterministic synthetic emissions."""
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import torch
from whisperx.alignment import align

from evaluate_whisperx_alignment import InputSpanSplitter, attribute_words, split_runs

torch.set_num_threads(2)
dictionary = {"[pad]": 0, "|": 1, "ا": 2, "ن": 3, "أ": 4, "ه": 5}


class SyntheticAcousticModel:
    def __call__(self, waveform):
        logits = torch.full((1, 28, len(dictionary)), -12.0)
        logits[:, :, 0] = 12.0
        for frame, character in zip([2, 5, 8, 11, 14, 17, 20], "أنا|هنا"):
            logits[0, frame, 0] = -12.0
            logits[0, frame, dictionary[character]] = 12.0
        return SimpleNamespace(logits=logits)


with patch("whisperx.alignment.nltk_load", return_value=InputSpanSplitter()):
    result = align([{"start": 0, "end": 2, "text": "أنا هنا"}],
                   SyntheticAcousticModel(), {"language": "ar", "dictionary": dictionary, "type": "huggingface"},
                   np.zeros(32000, dtype=np.float32), "cpu", interpolate_method="ignore")
words = result["word_segments"]
assert [w["word"] for w in words] == ["أنا", "هنا"]
boundary = (words[0]["end"] + words[1]["start"]) / 2
turns = [{"speaker_label": "A", "start_seconds": 0, "end_seconds": boundary},
         {"speaker_label": "B", "start_seconds": boundary, "end_seconds": 2}]
segments = split_runs(attribute_words(words, turns))
assert [s["speaker_label"] for s in segments] == ["A", "B"]
print("PASS: real WhisperX alignment and automatic speaker split; synthetic emissions only.")
