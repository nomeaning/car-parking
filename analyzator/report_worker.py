import logging
import queue

from device_session import DeviceSession
from report_sender import ReportSender

log = logging.getLogger("report_worker")


def report_worker(
    session: DeviceSession,
    report_sender: ReportSender,
    work_queue: "queue.Queue",
) -> None:
    """Send queued reports without blocking the video loop."""
    while True:
        captured_at, free_spaces, image_bytes = work_queue.get()
        try:
            report_sender.send_report(session, captured_at, free_spaces, image_bytes)
        except Exception:
            log.exception("Unexpected error in report worker")
        finally:
            work_queue.task_done()
