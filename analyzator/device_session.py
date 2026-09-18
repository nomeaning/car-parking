import os
import time
import json
import base64
import logging

import requests

from dotenv import load_dotenv
load_dotenv()

DEVICE_EMAIL = os.environ["DEVICE_EMAIL"]
DEVICE_PASSWORD = os.environ["DEVICE_PASSWORD"]


SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
AUTH_TOKEN_URL = f"{SUPABASE_URL}/auth/v1/token"
REPORT_INTERVAL_SECONDS = int(os.environ.get("REPORT_INTERVAL_SECONDS", 15))
TOKEN_REFRESH_BUFFER_SECONDS = 60

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("DeviceSession")

class DeviceSession:
    """Handles signing in as the device user and refreshing the session."""

    def __init__(self):
        self.access_token = None
        self.refresh_token = None
        self.expires_at = 0

    def _store(self, data: dict):
        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self.expires_at = time.time() + data["expires_in"]
        self._log_role_claim()

    def _log_role_claim(self):
        try:
            payload_b64 = self.access_token.split(".")[1]
            padded = payload_b64 + "=" * (-len(payload_b64) % 4)
            claims = json.loads(base64.urlsafe_b64decode(padded))
            role = claims.get("role")
            log.info("Signed in. Token role claim = %r", role)
            if role not in ["device", "authenticated"]:
                log.warning(
                    "Expected role claim 'device' or 'authenticated' but got %r.",
                    role,
                )
        except Exception as e:
            log.warning("Could not decode token for sanity check: %s", e)

    def sign_in(self):
        resp = requests.post(
            AUTH_TOKEN_URL,
            params={"grant_type": "password"},
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={"email": DEVICE_EMAIL, "password": DEVICE_PASSWORD},
            timeout=10,
        )
        resp.raise_for_status()
        self._store(resp.json())

    def refresh(self):
        resp = requests.post(
            AUTH_TOKEN_URL,
            params={"grant_type": "refresh_token"},
            headers={"apikey": SUPABASE_ANON_KEY, "Content-Type": "application/json"},
            json={"refresh_token": self.refresh_token},
            timeout=10,
        )
        resp.raise_for_status()
        self._store(resp.json())

    def get_valid_access_token(self) -> str:
        if self.access_token is None:
            self.sign_in()
        elif time.time() > self.expires_at - TOKEN_REFRESH_BUFFER_SECONDS:
            try:
                self.refresh()
            except requests.HTTPError:
                log.warning("Refresh failed, signing in fresh")
                self.sign_in()
        return self.access_token
