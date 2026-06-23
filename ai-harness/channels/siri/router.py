from fastapi import APIRouter, Depends

from infra.core.security import require_siri_auth
from channels.siri.schemas import SiriChatRequest, SiriChatResponse
from channels.siri.service import handle_siri_chat

router = APIRouter(dependencies=[Depends(require_siri_auth)])


@router.post("/chat", response_model=SiriChatResponse)
async def siri_chat(req: SiriChatRequest):
    return await handle_siri_chat(req)


