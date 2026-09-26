"""In-memory agent event bus - survives workflow timeouts/crashes.

Events are emitted by every node and readable via GET /api/foodbridge/agents/events.
Bounded deque keeps memory flat during long demos.
"""
from collections import deque
from datetime import datetime, timezone
from typing import Dict, List, Optional

EventStatus = str  # "running" | "completed" | "failed"


class EventStore:
    def __init__(self, maxlen: int = 2000):
        self._events: deque = deque(maxlen=maxlen)

    def emit(self, workflow_id: str, agent: str, status: EventStatus, detail: str) -> Dict:
        event = {
            "workflow_id": workflow_id,
            "agent": agent,
            "status": status,
            "detail": detail,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._events.append(event)
        return event

    def list(self, workflow_id: Optional[str] = None, agent: Optional[str] = None, limit: int = 200) -> List[Dict]:
        out = []
        for ev in reversed(self._events):  # newest first
            if workflow_id and ev["workflow_id"] != workflow_id:
                continue
            if agent and ev["agent"] != agent:
                continue
            out.append(ev)
            if len(out) >= limit:
                break
        return out

    def clear(self) -> None:
        self._events.clear()


_store: Optional[EventStore] = None


def get_event_store() -> EventStore:
    global _store
    if _store is None:
        _store = EventStore()
    return _store
