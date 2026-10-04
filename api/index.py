"""Vercel entry point: the FastAPI app as one Python serverless function (vercel.json routes /api/* and /health here)."""
from p2e.main import app  # noqa: F401
