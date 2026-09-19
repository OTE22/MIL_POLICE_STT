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

Choose the environment first — it is the one decision that changes everything else.
Omit `--environment` and the script asks before it touches anything.

```bash
# Real cases
sudo ./deploy-central.sh --environment production \
     --hostname central.unit.local \
     --cert /etc/ssl/certs/unit.crt --key /etc/ssl/private/unit.key --force-tls

# Demo / training / integration
sudo ./deploy-central.sh --environment development --hostname localhost
```

Generates all secrets on first run into a mode-0600 `.env` and never regenerates them.
Prints the bootstrap admin password **once**.

> **Never installed this before?** Read
> [../docs/production-deployment.md](../docs/production-deployment.md) first — it explains
> what you are installing and what to decide. This file is the quick reference.

### Setting the address on site (air-gapped)

Build and test wherever is convenient, then give the machine its real address as the last
step — it takes under a minute and touches no data:

```bash
sudo ./deploy-central.sh --reconfigure-address \
     --hostname central.unit.local --ip 192.168.10.50
```

Re-issues the certificate for the new name/IPs (keeping a timestamped copy of the old
one), recreates nginx so the new bind address actually takes effect, and re-checks DNS.
Nothing is rebuilt, no migration runs, and the signing key is unchanged — so the desktops
only need their `AGENT_CENTRAL_URL` pointed at the new address.

### Reaching the server

```bash
--hostname central.unit.local --ip 192.168.10.50   # name + static IP, both in the cert
--hostname 192.168.10.50                           # no DNS at all; the IP IS the name
--extra-name central                               # an alias, repeatable
--bind 192.168.10.50                               # publish on one interface only
```

`--ip` is repeatable and defaults to this machine's detected addresses, so a static-IP
server works by IP without being told. The deployment checks whether the hostname
resolves to this machine and, if not, prints the DNS A record, the hosts-file line for
Linux and Windows, and the option of using the IP directly.

|  | production | development |
|---|---|---|
| TLS | real certificate required | self-signed by default |
| Test database, dev dependencies | no | yes |
| الصياغة بالفصحى (Arabic formalization) | **local runtime only** — no cloud call is possible, it is refused in code | may use the hosted NVIDIA catalogue, **synthetic or anonymised text only** |
| Report template | an **approved** Word file must be uploaded and activated before a final محضر can be issued | ships a `نموذج غير معتمد` template that works immediately |
| Cloud API key on the machine | must not be present (warned about, and ignored) | optional, via `--nvidia-key FILE` → `secrets/nvidia_api_key` |

Step 6 of the run reports which formalization runtime resolved and why, and step 7
says whether an approved template is active. Both "available" and "unavailable" are
acceptable outcomes: the محضر is always writable by hand.

### Backing up a production server

`secrets/` (signing keys), `storage/recordings`, **`storage/reports`** (issued محاضر) and
**`storage/report-templates`** (the layout each one cites), plus a `pg_dump`. An issued
report is evidence; the template version it names must stay retrievable to verify it.

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
[WARN] these accounts have incomplete service details:
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
