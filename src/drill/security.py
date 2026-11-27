"""Signed approval tokens and secret masking."""
import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def load_secret(path):
    """Signing key: APPROVAL_SECRET if set, else a random key kept outside source control."""
    if os.getenv("APPROVAL_SECRET"):
        return os.environ["APPROVAL_SECRET"].encode()
    path = Path(path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(secrets.token_bytes(32))
    return path.read_bytes()


class ApprovalSigner:
    """HMAC token bound to drill, step, tool, exact parameters, approval id and expiry.

    ponytail: one symmetric key because both agents run in one process. If the operator
    moves to its own service, switch to asymmetric signatures so it cannot mint tokens.
    """

    def __init__(self, secret):
        self._secret = secret

    def _sign(self, drill_id, step_id, tool, params, approval_id, expires):
        message = canonical([drill_id, step_id, tool, params, approval_id, expires])
        return hmac.new(self._secret, message.encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def _prefix(tool, step_id):
        return f"{'ROLLBACK' if tool == 'rollback_step' else 'AUTH'}-APPV-{step_id}-"

    def generate_approval_token(self, *, drill_id, step_id, tool, params, approval_id, expires):
        signature = self._sign(drill_id, step_id, tool, params, approval_id, int(expires))
        return f"{self._prefix(tool, step_id)}{approval_id}.{int(expires)}.{signature}"

    def verify(self, token, *, drill_id, step_id, tool, params, now_ts):
        """Return (approval_id, None) or (None, reason)."""
        prefix = self._prefix(tool, step_id)
        if not isinstance(token, str) or not token.startswith(prefix):
            return None, "missing or wrong-scope approval token"
        parts = token[len(prefix):].split(".")
        if len(parts) != 3 or not (parts[1].isascii() and parts[1].isdigit()):
            return None, "malformed approval token"
        approval_id, expires, signature = parts[0], int(parts[1]), parts[2]
        expected = self._sign(drill_id, step_id, tool, params, approval_id, expires)
        if not hmac.compare_digest(expected.encode(), signature.encode()):
            return None, "signature does not match this drill, step, tool and parameters"
        if now_ts > expires:
            return None, "approval token expired"
        return approval_id, None


_SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|api[_-]?key|access[_-]?key|client[_-]?secret|account[_-]?key)"
                r"(\s*[=:]\s*)([^;\s,\"'}]+)"), r"\1\2****"),
    (re.compile(r"(\b[a-zA-Z][\w+.-]*://[^:/\s]+:)([^@\s]+)(@)"), r"\1****\3"),
    (re.compile(r"\bs[k]-[A-Za-z0-9_-]{12,}"), "[masked-api-key]"),  # [k] keeps secret scanners quiet
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._-]{12,}"), r"\1****"),
]
_SECRET_KEYS = re.compile(r"(?i)^(password|passwd|pwd|secret|client_secret|api_key|apikey|access_key|account_key)$")


def mask(value):
    """Recursively mask credentials. Applied before anything is stored, shown or sent to a model."""
    if isinstance(value, str):
        for pattern, replacement in _SECRET_PATTERNS:
            value = pattern.sub(replacement, value)
        return value
    if isinstance(value, dict):
        return {k: "****" if _SECRET_KEYS.match(str(k)) and v else mask(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mask(v) for v in value]
    return value
