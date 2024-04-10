from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Optional
from models import STANDARD_ERRORS_BY_CODE


router = APIRouter()


class ConsiderExtendedClassesPackRequest(BaseModel):
    emotion: str = Field(description="The emotion word the user selected")


@router.post(
    "/consider",
    status_code=204,
    responses=STANDARD_ERRORS_BY_CODE,
)
async def consider_extended_classes_pack(
    args: ConsiderExtendedClassesPackRequest,
    authorization: Optional[str] = Header(None),
):
    """Left for backwards compatibility. Always returns 204."""
    return Response(status_code=204)
