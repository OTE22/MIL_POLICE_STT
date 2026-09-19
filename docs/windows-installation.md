# Windows workstation installation

**Who this is for:** whoever sets up an interviewing computer running Windows. Follow it
in order; you do not need to understand the AI. Allow 20-45 minutes, mostly downloading.

**Setting up the SERVER instead?** That is [production-deployment.md](production-deployment.md).

The Local AI Agent is installed as a normal background application — Docker Desktop is
**not** required on investigator desktops. (A Docker variant exists for development, see
`desktop-agent/docker-compose.yml`.)

## Prerequisites

1. Windows 10/11 64-bit, administrator rights for installation.
2. **Python 3.11 or 3.12** (x64) from python.org, "Add to PATH" enabled.
3. **FFmpeg** (e.g. gyan.dev "full" build) with `ffmpeg.exe` and `ffprobe.exe` on the
   *system* PATH.
4. For GPU processing: NVIDIA driver ≥ 550 (CUDA 12.4 runtime is shipped in the torch wheels).
5. Network access to the central server (`https://central…:8443`).

## Install (spec §77 steps 1–3, 7–9)

```powershell
# elevated PowerShell, from the unpacked desktop-agent folder
Set-ExecutionPolicy -Scope Process Bypass
.\windows\install_agent.ps1 -CentralUrl https://central.unit.local:8443 -Compute gpu   # or -Compute cpu
```

The script copies the application to `C:\ProgramData\InvestigationAI\app`, creates
`C:\ProgramData\InvestigationAI\venv`, installs PyTorch (CPU or CUDA) + NeMo + Transformers,
writes `.env`, and registers **MilitarySTTAgent**:

* as a Windows service if **NSSM** (`nssm.exe`) is on the PATH (recommended), or
* as a Task-Scheduler task that starts at boot as SYSTEM and restarts on failure.

Either way the investigator never starts Python manually; the agent listens on
`http://127.0.0.1:17117` after every reboot.

## Install the central verification key (step 8)

```powershell
Invoke-RestMethod https://central.unit.local:8443/api/local-processing/public-key |
  Select-Object -ExpandProperty public_key_pem |
  Set-Content C:\ProgramData\InvestigationAI\central_public_key.pem -Encoding ASCII
```

or copy the file handed out by the administrator. The private key never leaves the server.

## Provision the models (steps 4–6)

```powershell
$py = "C:\ProgramData\InvestigationAI\venv\Scripts\python.exe"
$env:HF_TOKEN = "hf_..."          # one-time, only for the gated Cohere download
& $py C:\ProgramData\InvestigationAI\app\scripts\provision_models.py --model-dir C:\ProgramData\InvestigationAI\models
```

Or copy an offline bundle (see offline-provisioning.md) into
`C:\ProgramData\InvestigationAI\models\`.

## Verify (steps 9–12)

```powershell
& $py C:\ProgramData\InvestigationAI\app\scripts\healthcheck.py --load
& $py C:\ProgramData\InvestigationAI\app\scripts\run_transcription_test.py sample_arabic.wav
& $py C:\ProgramData\InvestigationAI\app\scripts\run_diarization_test.py two_speakers.wav --expect SPEAKER_00,SPEAKER_01,SPEAKER_00
Invoke-RestMethod http://127.0.0.1:17117/capabilities
```

## Register the workstation (step 13)

Log in to the central web application on that desktop, open any session → **التسجيل** →
the "حالة المعالجة المحلية" panel → **تسجيل محطة العمل**. The workstation then appears under
"حالة محطات العمل". (It is also registered automatically the first time a job is synchronized.)

## Updating

Re-run `install_agent.ps1` (it mirrors the application folder and restarts the service).
Model revisions are pinned; a new model revision is a deliberate change of `.env`
(`AGENT_*_MODEL_REVISION`) followed by re-provisioning — never automatic.

## Uninstall

```powershell
.\windows\uninstall_agent.ps1            # keeps models and data
.\windows\uninstall_agent.ps1 -Purge     # removes C:\ProgramData\InvestigationAI entirely
```
