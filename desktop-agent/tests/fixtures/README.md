# Test fixtures

* `conversation_ar_2spk.wav` — 52 s, 16 kHz mono. Two distinct Arabic voices in the
  pattern **A → B → A → B → A** (investigator / interviewee) with 0.9 s pauses.
  Synthesized with Microsoft neural TTS voices (`ar-LB-RamiNeural`, `ar-EG-SalmaNeural`);
  the script is in `conversation_script.json`. Used by the real diarization / STT acceptance
  tests and the browser E2E. It is synthetic speech, not a human field recording — replace
  with a real interview recording for final acceptance in the unit.
* `single_speaker_ar.wav` — one turn of the same conversation (transcription test).
