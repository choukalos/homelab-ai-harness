from fastapi import APIRouter, Depends

from core.security import require_siri_auth
from siri.schemas import SiriChatRequest, SiriChatResponse
from siri.service import handle_siri_chat

router = APIRouter(dependencies=[Depends(require_siri_auth)])


@router.post("/chat", response_model=SiriChatResponse)
async def siri_chat(req: SiriChatRequest):
    return await handle_siri_chat(req)


