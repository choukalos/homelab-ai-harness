"""FastAPI router for the scheduler.

Endpoints (all under /schedules)
-----
GET    /schedules              — list all schedules (JSON + plain text)
GET    /schedules/{id}         — single schedule detail
POST   /schedules              — create a new schedule
PATCH  /schedules/{id}         — partial update
DELETE /schedules/{id}         — remove a schedule
POST   /schedules/{id}/trigger — fire a schedule immediately
POST   /schedules/condition    — trigger a named condition event
GET    /schedules/text         — human-readable summary (for voice/chat)
POST   /schedules/chat         — NLP command handler for chat assistants
"""

from fastapi import APIRouter, HTTPException

from scheduler.schemas import (
    ConditionTriggerRequest,
    CreateScheduleRequest,
    ScheduleResponse,
    UpdateScheduleRequest,
)
from scheduler.service import (
    create_schedule,
    delete_schedule,
    describe_schedules_as_text,
    fire_condition_event,
    get_schedule,
    list_schedules,
    manual_trigger,
    process_schedule_command,
    update_schedule,
)

router = APIRouter()


@router.get("", response_model=list[ScheduleResponse])
def list_api():
    """Return every persisted schedule."""
    return list_schedules()


@router.post("", response_model=ScheduleResponse)
def create_api(req: CreateScheduleRequest):
    """Create a new schedule."""
    return create_schedule(req)


# --- fixed-string paths BEFORE parameterized /{schedule_id} ---

@router.get("/text", responses={200: {"content": {"text/plain": {}}}})
def list_text():
    """Return a plain-text summary of schedules (for Siri, voice, chat)."""
    return describe_schedules_as_text()


@router.post("/condition")
def condition_api(req: ConditionTriggerRequest):
    """Trigger a named condition event.  All matching condition-schedules
    will pick it up within ~15 seconds via the condition checker."""
    return fire_condition_event(req)


@router.post("/chat")
def chat_api(req: dict):
    """Accept free-form text describing a schedule command.

    The body should be ``{"command": "pause morning briefing"}``
    or ``{"command": "what schedules do I have?"}``.

    Returns a plain-text response suitable for chat / voice output.
    """
    command = req.get("command", req.get("text", ""))
    if not command:
        raise HTTPException(status_code=400, detail="Need 'command' or 'text' key")
    return {"response": process_schedule_command(command)}


# --- parameterized paths (must come after fixed-string paths) ---

@router.get("/{schedule_id}", response_model=ScheduleResponse)
def get_api(schedule_id: str):
    """Fetch a single schedule by ID."""
    resp = get_schedule(schedule_id)
    if resp is None:
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")
    return resp


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
def update_api(schedule_id: str, req: UpdateScheduleRequest):
    """Partially update a schedule (set only the fields you provide)."""
    return update_schedule(schedule_id, req)


@router.delete("/{schedule_id}")
def delete_api(schedule_id: str):
    """Remove a schedule permanently."""
    if not delete_schedule(schedule_id):
        raise HTTPException(status_code=404, detail=f"Schedule {schedule_id} not found")
    return {"ok": True}


@router.post("/{schedule_id}/trigger")
def trigger_api(schedule_id: str):
    """Fire a schedule immediately without waiting for its next tick."""
    return manual_trigger(schedule_id)

