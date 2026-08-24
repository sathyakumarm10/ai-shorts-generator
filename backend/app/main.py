"""Entry point for the AI Shorts Generator FastAPI application.

This module currently only exposes a couple of basic endpoints to confirm
that the backend is set up correctly. More functionality (video processing,
AI features, etc.) will be added in later stages of the project.
"""

from fastapi import FastAPI

# Create the FastAPI application instance.
app = FastAPI(title="AI Shorts Generator API")


@app.get("/")
def read_root():
    """Basic endpoint to confirm the API is running."""
    return {"message": "AI Shorts Generator API is running"}


@app.get("/health")
def health_check():
    """Simple health check endpoint used to verify the service is alive."""
    return {"status": "ok"}
