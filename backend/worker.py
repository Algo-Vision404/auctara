"""Standalone worker entrypoint for a separate Render worker service.

Runs ONLY the scheduled-task polling loop (app/scheduler.py) against the
same SQLite database (WAL mode) as the web service. No HTTP server here.

Use this instead of the in-process scheduler when deploying the web and
worker as two separate Render services: set RUN_SCHEDULER_INPROCESS=false
on the web service, and run this file as the worker service's start
command, so recurring agent commerce keeps firing even if the web dyno
restarts, scales, or is temporarily down, and is never triggered twice.

Local/dev usage (this sandbox, docker-compose) doesn't need this file at
all: Settings.run_scheduler_inprocess defaults to True, so the web process
already polls for due schedules on its own.
"""
from __future__ import annotations

import asyncio
import logging

from app.database.migrations import run_migrations
from app.scheduler import scheduler_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("auctara.worker")


async def main() -> None:
    run_migrations()
    logger.info("Auctara worker started: polling for due scheduled tasks.")
    await scheduler_loop()


if __name__ == "__main__":
    asyncio.run(main())
