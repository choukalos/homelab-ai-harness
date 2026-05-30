from pydantic import BaseModel, Field
from typing import Optional


class DemoRequest(BaseModel):
    title: str = Field(..., description="Demo title")
    prompt: str = Field(..., description="Product/demo prompt")
    model: Optional[str] = None
    save_name: Optional[str] = None


class DemoResponse(BaseModel):
    title: str
    filename: str
    url: str
    html: str


