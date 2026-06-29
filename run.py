"""Convenience launcher: `python run.py` -> uvicorn on :8080."""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.getenv("PGDUTY_HOST", "0.0.0.0"),
        port=int(os.getenv("PGDUTY_PORT", "8080")),
        reload=bool(os.getenv("PGDUTY_RELOAD")),
    )
