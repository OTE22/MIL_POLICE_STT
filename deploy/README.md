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

Both scripts take `--help`, are idempotent, and stop at the first failed check.
