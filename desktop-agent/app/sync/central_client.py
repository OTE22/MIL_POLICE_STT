"""HTTP client for the central FastAPI server (authenticated with the job's processing token)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings

log = logging.getLogger(__name__)


class CentralError(Exception):
    def __init__(self, code: str, message: str, *, status: int | None = None, permanent: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.permanent = permanent


class CentralClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        verify: bool | str = settings.central_verify_tls
        if settings.central_ca_bundle:
            verify = str(settings.central_ca_bundle)
        self._client = httpx.Client(
            base_url=settings.central_url.rstrip("/"),
            timeout=httpx.Timeout(settings.central_timeout_seconds, connect=10.0),
            verify=verify,
        )

    @property
    def enabled(self) -> bool:
        return self._settings.central_sync_enabled

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _raise_for(resp: httpx.Response) -> None:
        if resp.is_success:
            return
        detail = ""
        try:
            body = resp.json()
            detail = body.get("detail") if isinstance(body, dict) else str(body)
        except Exception:  # noqa: BLE001
            detail = resp.text[:200]
        permanent = resp.status_code in (400, 401, 403, 404, 409, 422)
        raise CentralError(str(detail or f"http_{resp.status_code}"), f"central responded {resp.status_code}: {detail}", status=resp.status_code, permanent=permanent)

    def _post_json(self, path: str, token: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = self._client.post(path, json=payload, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            raise CentralError("network", f"{type(exc).__name__}: {exc}") from exc
        self._raise_for(resp)
        return resp.json() if resp.content else {}

    # --------------------------------------------------------------- endpoints
    def report_state(self, job_id: str, token: str, state: str, *, progress: float | None = None, message: str | None = None, failure_stage: str | None = None, workstation: dict | None = None) -> None:
        """Best-effort progress report (never raises)."""
        if not self.enabled:
            return
        try:
            self._post_json(
                f"/api/local-processing/{job_id}/state",
                token,
                {"state": state, "progress": progress, "message": message, "failure_stage": failure_stage, "workstation": workstation},
            )
        except CentralError as exc:
            log.debug("state report failed for %s: %s", job_id, exc.message)

    def submit_result(self, job_id: str, token: str, result: dict[str, Any]) -> dict[str, Any]:
        return self._post_json(f"/api/local-processing/{job_id}/result", token, result)

    def upload_audio(self, job_id: str, token: str, path: Path, filename: str, mime_type: str) -> dict[str, Any]:
        try:
            with path.open("rb") as fh:
                resp = self._client.post(
                    f"/api/local-processing/{job_id}/audio",
                    files={"file": (filename, fh, mime_type)},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=httpx.Timeout(max(self._settings.central_timeout_seconds, 600.0), connect=10.0),
                )
        except httpx.HTTPError as exc:
            raise CentralError("network", f"{type(exc).__name__}: {exc}") from exc
        self._raise_for(resp)
        return resp.json() if resp.content else {}

    def health(self) -> bool:
        try:
            resp = self._client.get("/api/health", timeout=5.0)
            return resp.is_success
        except httpx.HTTPError:
            return False
