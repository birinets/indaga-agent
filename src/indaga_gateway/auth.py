"""Device-token pairing for a single-owner personal server.

Flow (no accounts, no multi-tenant identity — there is one owner and their devices):
  1. The owner runs `python -m indaga_gateway pair-code` on the server. It mints a short-lived 6-digit
     pairing code (stored at ~/.indaga/<subject>/gateway-pairing.json, 0600, 10-min TTL) and prints it.
  2. The phone, during onboarding, POSTs the code to /v1/pair and receives a long-lived device token.
     We store only the token's SHA-256 in ~/.indaga/<subject>/gateway-devices.json (0600); the phone
     keeps the raw token in the iOS Keychain. The pairing code is one-time (consumed on redemption).
  3. Every request carries `Authorization: Bearer <token>`; we SHA-256 it and check membership.
  Revoke = remove the entry from gateway-devices.json.

Tokens are bound to the subject they were paired against (n=1). The gateway serves exactly one subject,
so a token is only ever checked against that subject's device list.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time

from indaga.runtime import paths

_PAIRING_TTL_SECONDS = 600  # 10 minutes


def _pairing_path(subject_id: str):
    return paths.subject_dir(subject_id) / "gateway-pairing.json"


def _devices_path(subject_id: str):
    return paths.subject_dir(subject_id) / "gateway-devices.json"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> int:
    return int(time.time())


# -- pairing code ----------------------------------------------------------- #

def mint_pairing_code(subject_id: str) -> str:
    """Generate + persist a one-time 6-digit pairing code; return it for display to the owner."""
    d = paths.subject_dir(subject_id)
    paths.secure_dir(d)
    code = f"{secrets.randbelow(1_000_000):06d}"
    p = _pairing_path(subject_id)
    p.write_text(json.dumps({"code_sha256": _sha256(code), "expires_at": _now() + _PAIRING_TTL_SECONDS}),
                 encoding="utf-8")
    paths.secure_file(p)
    return code


def redeem_pairing_code(subject_id: str, code: str, *, label: str = "iphone") -> str | None:
    """Verify a pairing code (unexpired, matching, one-time) and mint a device token. Returns the raw
    token on success (shown to the client ONCE) or None on failure."""
    p = _pairing_path(subject_id)
    if not p.exists():
        return None
    try:
        rec = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if _now() > int(rec.get("expires_at", 0)):
        p.unlink(missing_ok=True)
        return None
    if not secrets.compare_digest(_sha256(code), str(rec.get("code_sha256", ""))):
        return None
    token = secrets.token_urlsafe(32)  # 256-bit
    _append_device(subject_id, _sha256(token), label)
    p.unlink(missing_ok=True)  # one-time use
    return token


# -- device tokens ---------------------------------------------------------- #

def _load_devices(subject_id: str) -> list[dict]:
    p = _devices_path(subject_id)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _append_device(subject_id: str, token_sha256: str, label: str) -> None:
    devices = _load_devices(subject_id)
    devices.append({"token_sha256": token_sha256, "label": label, "paired_at": _now()})
    p = _devices_path(subject_id)
    p.write_text(json.dumps(devices), encoding="utf-8")
    paths.secure_file(p)


def verify_token(subject_id: str, token: str) -> bool:
    """Constant-time check that a bearer token was paired with this subject."""
    target = _sha256(token)
    return any(secrets.compare_digest(target, d.get("token_sha256", "")) for d in _load_devices(subject_id))
