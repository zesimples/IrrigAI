"""Standalone scheduler worker — runs APScheduler only, no HTTP server.

Start with:
    python -m app.worker

In production this is a separate docker-compose service (`worker`) so the
HTTP server never runs scheduled jobs. A single replica of this service
guarantees exactly-one execution; Redis job locks provide belt-and-suspenders
protection against concurrent runs during restarts.
"""

import asyncio
import logging
import signal

logger = logging.getLogger(__name__)
logging.basicConfig(
    level="INFO",
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


async def main() -> None:
    from app.services.scheduler import start_scheduler, stop_scheduler

    logger.info("IrrigAI worker starting...")
    start_scheduler()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _shutdown(*_):
        logger.info("IrrigAI worker shutting down...")
        loop.call_soon_threadsafe(stop_event.set)

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _shutdown)

    await stop_event.wait()
    stop_scheduler()
    logger.info("IrrigAI worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
