import asyncio
import json
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_db
from src.db.models.contribution import ContributionEvent
from src.db.models.job import JobStatus, ScrapeJob
from src.db.models.repository import Repository

router = APIRouter()

# In-memory log buffer and connected clients
log_buffer: deque[dict[str, Any]] = deque(maxlen=1000)
connected_clients: set[WebSocket] = set()


class LogBroadcaster:
    """Broadcasts logs to all connected WebSocket clients."""

    @staticmethod
    async def broadcast(message: dict[str, Any]) -> None:
        """Send message to all connected clients."""
        log_buffer.append(message)
        disconnected = set()

        for client in connected_clients:
            try:
                await client.send_json(message)
            except Exception:
                disconnected.add(client)

        # Clean up disconnected clients
        for client in disconnected:
            connected_clients.discard(client)

    @staticmethod
    async def log(level: str, message: str) -> None:
        """Log a message and broadcast to clients."""
        log_entry = {
            "type": "log",
            "level": level,
            "message": message,
            "timestamp": datetime.utcnow().isoformat(),
        }
        await LogBroadcaster.broadcast(log_entry)


# Global broadcaster instance
broadcaster = LogBroadcaster()


def get_template_path() -> Path:
    """Get the path to the templates directory."""
    return Path(__file__).parent.parent / "templates"


@router.get("/", response_class=HTMLResponse)
async def dashboard_page() -> HTMLResponse:
    """Serve the monitoring dashboard."""
    template_path = get_template_path() / "dashboard.html"
    return HTMLResponse(content=template_path.read_text(encoding="utf-8"))


@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket) -> None:
    """WebSocket endpoint for live log streaming."""
    await websocket.accept()
    connected_clients.add(websocket)

    try:
        # Send recent logs from buffer
        for log_entry in list(log_buffer)[-50:]:
            await websocket.send_json(log_entry)

        # Keep connection alive and handle incoming messages
        while True:
            try:
                # Wait for any message (ping/pong or commands)
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                # Send periodic stats update
                pass

    except WebSocketDisconnect:
        pass
    finally:
        connected_clients.discard(websocket)


@router.get("/stats")
async def get_dashboard_stats(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """Get current dashboard statistics."""
    # Count active jobs
    active_jobs_result = await db.execute(
        select(func.count(ScrapeJob.id)).where(
            ScrapeJob.status == JobStatus.RUNNING
        )
    )
    active_jobs = active_jobs_result.scalar() or 0

    # Count repositories
    repo_count_result = await db.execute(select(func.count(Repository.id)))
    repo_count = repo_count_result.scalar() or 0

    # Count events
    event_count_result = await db.execute(select(func.count(ContributionEvent.id)))
    event_count = event_count_result.scalar() or 0

    # Count errors in last 24 hours
    yesterday = datetime.utcnow() - timedelta(hours=24)
    error_count_result = await db.execute(
        select(func.count(ScrapeJob.id)).where(
            ScrapeJob.status == JobStatus.FAILED,
            ScrapeJob.completed_at >= yesterday,
        )
    )
    error_count = error_count_result.scalar() or 0

    return {
        "active_jobs": active_jobs,
        "repositories": repo_count,
        "events": event_count,
        "errors_24h": error_count,
    }


@router.get("/errors")
async def get_recent_errors(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Get recent job errors."""
    result = await db.execute(
        select(ScrapeJob)
        .where(ScrapeJob.status == JobStatus.FAILED)
        .order_by(ScrapeJob.completed_at.desc())
        .limit(limit)
    )
    jobs = result.scalars().all()

    return [
        {
            "id": job.id,
            "repository_id": job.repository_id,
            "job_type": job.job_type.value,
            "error_message": job.error_message,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
        for job in jobs
    ]


# Helper function to log from anywhere in the application
async def log_info(message: str) -> None:
    await broadcaster.log("info", message)


async def log_error(message: str) -> None:
    await broadcaster.log("error", message)


async def log_warning(message: str) -> None:
    await broadcaster.log("warning", message)


async def log_debug(message: str) -> None:
    await broadcaster.log("debug", message)
