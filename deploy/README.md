# deploy/

Production deployment kit. The full guide is
[docs/production-deployment.md](../docs/production-deployment.md).

```
deploy/
├── deploy-central.sh      run on the server   — web app, database, TLS
├── deploy-edge.sh         run on each desktop — Local AI Agent + the models
├── model-manifests/       pinned revision + SHA-256 of every model file
└── central_public_key.pem written by deploy-central.sh; carry it to the desktops
```

## Server

```bash
sudo ./deploy-central.sh --hostname central.unit.local \
     --cert /etc/ssl/certs/unit.crt --key /etc/ssl/private/unit.key --force-tls
```

Generates all secrets on first run into a mode-0600 `.env` and never regenerates them.
Prints the bootstrap admin password **once**.

## Investigator desktop

Put the downloaded models next to this script — any layout, they are found by content:

```
deploy/models/cohere-transcribe-arabic-07-2026/
deploy/models/diar_streaming_sortformer_4spk-v2.1/
deploy/models/speakerverification_speakernet/
```

```bash
sudo ./deploy-edge.sh --central-url https://central.unit.local:8443 \
     --public-key ./central_public_key.pem --compute gpu --load-models
```

Every model file is checked against the pinned size **and SHA-256** in `model-manifests/`
before anything is installed. A tampered or truncated model is refused and nothing is
staged — re-download it rather than working around the check.

`speakerverification_speakernet` is the one **optional** model: leave it out and the agent
still transcribes and diarizes normally, but no voice prints are ever produced and
بصمات الأصوات stays empty. The script says which of the two you got.

Both scripts take `--help`, are idempotent, and stop at the first failed check.

### First run on the server

`الجهاز` + `الرقم العسكري` produce a user's `الرقم المرجعي`. Both are **mandatory** for every
account created through the interface, but the bootstrap administrator is seeded directly and
has neither — so it cannot be bound to a speaker or carry a voice print until you complete it
in **إدارة المستخدمين**. `deploy-central.sh` names any such account at the end of its run:

```
[WARN] these accounts have no الرقم المرجعي and cannot be identified as speakers:
           مدير النظام
```

Inventing a serial for it would risk colliding with a real person's, so the script reports the
gap rather than filling it.

### Verifying voice identification after deploying

```bash
curl -s http://127.0.0.1:17117/model-status | tr ',' '
' | grep -A 6 '"speaker_id"'
```

| What you get | Meaning |
|---|---|
| `"state":"READY"` / `"PROVISIONED"` | working; `PROVISIONED` simply means not loaded yet |
| `"state":"NOT_PROVISIONED"` | the model was not staged — re-run with it present |
| **no output at all** | this agent build predates voice identification; redeploy a current image |

The last row is worth checking explicitly. In the interface a missing *capability* and a
missing *embedding* look identical on the speaker card, and the advice it offers
("reprocess the recording") does nothing when the agent has no model to run.

## Clearing a demo system

```bash
../scripts/reset_demo_data.sh --yes
```

Empties operational data and stored files, keeps accounts. Refuses unless the environment is
development, demo or test.

## Upgrading over existing data

The identity backfill refuses, rather than guesses, when one reference number is recorded under
two different names. `deploy-central.sh` surfaces that specific failure with the offending
references so it can be resolved and re-run.
