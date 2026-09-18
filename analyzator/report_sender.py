import logging
import os
import time
import requests

from datetime import datetime

from dotenv import load_dotenv
from device_session import DeviceSession

load_dotenv()

# --- Supabase reporting config ---
SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_ANON_KEY = os.environ["SUPABASE_ANON_KEY"]
FUNCTION_URL = f"{SUPABASE_URL}/functions/v1/report-parking-status"
REPORT_MAX_RETRIES = 3
REPORT_TIMEOUT_SECONDS = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("main")

class ReportSender:
    def send_report(self, session: DeviceSession, captured_at: datetime, free_spaces: int, image_bytes: bytes):
        token = session.get_valid_access_token()

        for attempt in range(1, REPORT_MAX_RETRIES + 1):
            try:
                start = time.time()
                resp = requests.post(
                    FUNCTION_URL,
                    headers={
                        "apikey": SUPABASE_ANON_KEY,
                        "Authorization": f"Bearer {token}",
                    },
                    data={
                        "time": captured_at.isoformat(),
                        "free_spaces": str(free_spaces),
                    },
                    files={"image": ("snapshot.jpg", image_bytes, "image/jpeg")},
                    timeout=REPORT_TIMEOUT_SECONDS,
                )
                elapsed = time.time() - start

                if resp.status_code == 200:
                    log.info("Reported free_spaces=%d in %.1fs -> %s", free_spaces, elapsed, resp.json())
                    return
                else:
                    log.error(
                        "Report attempt %d/%d failed [%s] in %.1fs: %s",
                        attempt, REPORT_MAX_RETRIES, resp.status_code, elapsed, resp.text,
                    )

            except requests.exceptions.RequestException as e:
                log.error("Report attempt %d/%d raised %s: %s", attempt, REPORT_MAX_RETRIES, type(e).__name__, e)

            if attempt < REPORT_MAX_RETRIES:
                backoff = 2 ** attempt
                log.info("Retrying in %ds...", backoff)
                time.sleep(backoff)

        log.error("Giving up on this report after %d attempts", REPORT_MAX_RETRIES)