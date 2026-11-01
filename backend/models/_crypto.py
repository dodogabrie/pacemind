"""Shared Fernet cipher for at-rest token encryption.

Lives here (rather than on a model) so every model that stores OAuth tokens
uses the same key lifecycle — one dev-key file, one place to rotate.
"""

import os
import logging

from cryptography.fernet import Fernet
from pathlib import Path

logger = logging.getLogger(__name__)

# Generate encryption key (store in .env in production)
ENCRYPTION_KEY = os.getenv('ENCRYPTION_KEY')
if ENCRYPTION_KEY:
    ENCRYPTION_KEY = ENCRYPTION_KEY.encode()
else:
    # Dev-friendly fallback: persist a stable key on disk to avoid invalidating
    # encrypted tokens every time the server restarts.
    key_path = Path(__file__).resolve().parents[1] / 'instance' / 'encryption_key'
    try:
        if key_path.exists():
            ENCRYPTION_KEY = key_path.read_bytes().strip()
        else:
            key_path.parent.mkdir(parents=True, exist_ok=True)
            ENCRYPTION_KEY = Fernet.generate_key()
            key_path.write_bytes(ENCRYPTION_KEY)
            try:
                os.chmod(key_path, 0o600)
            except Exception:
                pass
            logger.warning(f"ENCRYPTION_KEY not set; generated dev key at {key_path} (tokens will depend on this file)")
    except Exception:
        ENCRYPTION_KEY = Fernet.generate_key()

cipher = Fernet(ENCRYPTION_KEY)
