"""Worker entrypoint. The APScheduler loop is added in milestone 5."""

import logging
import time

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("worker")

if __name__ == "__main__":
    log.info("worker started (idle until scheduler lands in milestone 5)")
    while True:
        time.sleep(60)
