"""Run the Visa Disputes Processing Brain server."""

import os

import uvicorn


def main() -> None:
    """Start the FastAPI server."""
    reload = os.environ.get("RELOAD", "false").lower() in ("1", "true", "yes")
    uvicorn.run(
        "src.app:app",
        host="0.0.0.0",
        port=8000,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
