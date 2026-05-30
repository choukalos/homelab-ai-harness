from fastapi import APIRouter, Depends

from core.security import require_auth
from pm_demo.schemas import DemoRequest, DemoResponse
from pm_demo.service import generate_demo_html

router = APIRouter(tags=["pm-demo"])


@router.post("/demo", response_model=DemoResponse)
async def create_pm_demo(
    req: DemoRequest,
    _: None = Depends(require_auth),
):
    return await generate_demo_html(
        title=req.title,
        prompt=req.prompt,
        model=req.model,
        save_name=req.save_name,
    )


