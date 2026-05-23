from __future__ import annotations

import secrets
from datetime import datetime, timezone


def new_signal_id(prefix: str = "sig") -> str:
    """Lexicographically sortable, collision-resistant signal id."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{prefix}_{ts}_{secrets.token_hex(4)}"
