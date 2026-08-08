"""Vellum background worker entrypoint."""

from __future__ import annotations

import argparse
import logging
import os

from backend.jobs import worker_loop
from backend.register import ensure_register

logging.basicConfig(level=os.environ.get("VELLUM_LOG_LEVEL", "INFO"))
logger = logging.getLogger("vellum.worker")


def main() -> None:
    parser = argparse.ArgumentParser(description="Vellum job worker")
    parser.add_argument("--once", action="store_true", help="Process at most one job then exit")
    parser.add_argument("--poll", type=float, default=1.0, help="Seconds between empty polls")
    args = parser.parse_args()
    ensure_register()
    logger.info("Vellum worker starting (once=%s poll=%s)", args.once, args.poll)
    worker_loop(poll_seconds=args.poll, once=args.once)


if __name__ == "__main__":
    main()
