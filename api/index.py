"""Vercel entry point: the FastAPI app as one Python serverless function (vercel.json routes /api/* and /health here)."""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # the repo root, so `import p2e` works in the bundle

try:
    from p2e.main import app  # noqa: F401
except Exception as exc:                  # show why startup failed instead of Vercel's bare FUNCTION_INVOCATION_FAILED
    traceback.print_exc()                 # full trace in the Vercel function logs
    reason = f"{type(exc).__name__}: {str(exc)[:300]}"

    async def app(scope, receive, send):  # minimal ASGI app: every request answers 500 with the startup error
        if scope["type"] != "http":
            return
        await send({"type": "http.response.start", "status": 500, "headers": [(b"content-type", b"text/plain")]})
        await send({"type": "http.response.body", "body": f"P2E Bridge server failed to start: {reason}".encode()})
