"""FastAPI router for the deep_research workflow (Deep Agents with MySQL checkpointing)."""

from __future__ import annotations

import uuid
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from infra.core.security import require_auth
from research.deep_research.schemas import DeepResearchRequest, DeepResearchResponse
from research.deep_research.service import run_deep_research

router = APIRouter(tags=["deep-research"])


@router.post("/run", response_model=DeepResearchResponse)
async def run_deep_research_endpoint(
    req: DeepResearchRequest,
    _: None = Depends(require_auth),
) -> DeepResearchResponse:
    """Run the deep research agent on the given query.

    This is the skeleton proof-of-concept: a single search node to validate
    the end-to-end Deep Agents + MySQL checkpointing flow.
    """
    return await run_deep_research(req)


@router.post("/run/stream")
async def run_deep_research_stream(
    req: DeepResearchRequest,
    _: None = Depends(require_auth),
) -> StreamingResponse:
    """Stream the deep research output as the agent works.

    Yields SSE events as the agent processes tool calls and generates text.
    Useful for live UI updates while the agent is researching.
    """
    import json

    thread_id = req.thread_id or str(uuid.uuid4())

    from langchain_core.messages import HumanMessage
    from research.deep_research.service import get_deep_agent

    agent = get_deep_agent()

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    input_state = {
        "messages": [HumanMessage(content=req.query)],
    }

    async def _stream():
        yield json.dumps({"event": "start", "thread_id": thread_id, "query": req.query}) + "\n"

        try:
            async for event in agent.astream(input_state, config, stream_mode="updates"):
                # event is a tuple of (namespace, update_dict)
                if isinstance(event, tuple):
                    ns, update = event
                    yield json.dumps({
                        "event": "update",
                        "namespace": ns,
                        "update": _serialize_update(update),
                    }) + "\n"
                else:
                    yield json.dumps({
                        "event": "update",
                        "namespace": "default",
                        "update": _serialize_update(event),
                    }) + "\n"

            yield json.dumps({
                "event": "done",
                "thread_id": thread_id,
            }) + "\n"

        except Exception as e:
            yield json.dumps({
                "event": "error",
                "message": str(e),
            }) + "\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


def _serialize_update(update):
    """Convert update dict to JSON-serializable form, handling non-serializable types."""
    import json as _json

    # Handle LangChain message objects that might be in the update
    if isinstance(update, dict):
        result = {}
        for key, value in update.items():
            if hasattr(value, "model_dump"):
                result[key] = [v.model_dump() for v in value] if isinstance(value, list) else value.model_dump()
            elif hasattr(value, "dict"):
                result[key] = [v.dict() for v in value] if isinstance(value, list) else value.dict()
            else:
                result[key] = value
        return result
    return update
