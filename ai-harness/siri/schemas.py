from pydantic import BaseModel, Field


class SiriChatRequest(BaseModel):
    text: str
    session_id: str | None = None
    mode: str = "voice"
    intent: str = "chat"
    return_media: bool = True
    model: str | None = None


class SiriChatResponse(BaseModel):
    speak: str
    display: str
    session_id: str | None = None
    links: list[dict] = Field(default_factory=list)
    media: list[dict] = Field(default_factory=list)
    data: dict = Field(default_factory=dict)


