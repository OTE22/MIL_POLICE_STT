# Troubleshooting

| Symptom (Arabic UI) | Cause | Fix |
|---|---|---|
| الخدمة المحلية غير متوفرة | agent not running / wrong port / browser blocked the local-network request | `curl http://127.0.0.1:17117/health`; on Windows check service `MilitarySTTAgent` (`nssm status` / Task Scheduler); accept the browser's local-network permission prompt; make sure the central origin is in `AGENT_ALLOWED_ORIGINS` |
| النموذج غير جاهز (STT) | Cohere model not provisioned, integrity mismatch, or load error | `python scripts/healthcheck.py --load`; provision with `HF_TOKEN` (gated repo); check `AGENT_MODEL_DIR` |
| النموذج غير جاهز (diarization) | `.nemo` file missing or NeMo import error | provision `--only diarization`; check torch/NeMo installation in the venv |
| تعذر تشغيل نموذج … على هذا الجهاز | model load failed at job time (VRAM, corrupt files) | see `agent.err.log` / `docker compose logs agent`; run with `AGENT_STT_DEVICE=cpu` to confirm files are fine; free GPU memory |
| الملف الصوتي غير مدعوم | extension/MIME/magic bytes rejected | use WAV/MP3/M4A/WEBM; re-export with FFmpeg |
| تعذر معالجة التسجيل الصوتي | ffprobe/ffmpeg failure, empty or corrupted audio | `ffprobe file`; ensure FFmpeg is on the *system* PATH of the service account |
| تعذر إرسال النتائج إلى الخادم. سيتم إعادة المحاولة | central unreachable, TLS error | results are kept locally and retried (`GET /jobs/{id}` shows `sync_state`); fix `AGENT_CENTRAL_URL`, CA bundle; `POST /jobs/sync/run` forces a retry |
| انتهت صلاحية تصريح المعالجة | more than `CENTRAL_PROCESSING_TOKEN_ACCEPT_TTL_SECONDS` between token issue and upload, or clock skew | retry; synchronize clocks (agent allows ±60 s) |
| `public_key_missing` in agent logs | central public key not installed | copy `central_public_key.pem` (see installation docs) |
| `token_replay` | the same token was submitted twice | request a new processing token (the UI does this automatically on retry) |
| Session stuck in قيد المعالجة | agent crashed mid-job | the agent marks interrupted jobs FAILED on restart; cancel via **إلغاء المهمة** or the central cancel endpoint and process again |
| `sha256_mismatch` on audio upload | the original file changed between processing and upload | never edit files in the agent's job directory; process again |
| nginx 502 | backend not healthy yet / migration failing | `docker compose logs backend` |
| `CUDA requested but not available` | driver/toolkit mismatch | check `nvidia-smi`; the agent falls back to CPU and reports it |

Logs: central `docker compose logs -f backend nginx`; agent `docker compose logs -f agent`
or `C:\ProgramData\InvestigationAI\agent\agent.err.log` (NSSM) / `journalctl -u military-stt-agent`.
