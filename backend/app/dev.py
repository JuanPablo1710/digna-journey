"""Run the local server with a bounded shutdown."""

import sys

import uvicorn


GRACEFUL_SHUTDOWN_SECONDS = 2


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        reload=sys.platform != "win32",
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
    )
