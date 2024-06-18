import secrets
from fastapi import APIRouter, Header
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Annotated, Optional
from auth import auth_admin

from file_uploads.helper import FileUploadWithProgressResponse, start_upload
from itgs import Itgs
from models import STANDARD_ERRORS_BY_CODE

from admin.client_flows.image.models.dynamic_size import ClientFlowDynamicSize


class CreateClientFlowImageRequest(BaseModel):
    job: str = Field(
        description=(
            "The processor to use, i.e., the name of the runner in the jobs repo. "
            "This SHOULD match the `job` value within the `x-processor` extension information "
            "for the property on the screen that you intend to use this image for."
        )
    )
    file_size: int = Field(description="The size of the file in bytes")
    dynamic_size: Optional[ClientFlowDynamicSize] = Field(
        None,
        description=(
            "If a dynamic size is supported for the content as indicated via the "
            "x-dynamic-size hint, provides dynamic size information to forward "
            "to the processor."
        ),
    )


router = APIRouter()


@router.post(
    "/",
    response_model=FileUploadWithProgressResponse,
    responses=STANDARD_ERRORS_BY_CODE,
    status_code=201,
)
async def create_client_flow_image(
    args: CreateClientFlowImageRequest,
    authorization: Annotated[Optional[str], Header()] = None,
):
    """Begins the file upload process for a client flow image which will be processed
    by the given job.

    Requires standard authorization for an admin user.
    """
    async with Itgs() as itgs:
        auth_result = await auth_admin(itgs, authorization)
        if auth_result.result is None:
            return auth_result.error_response

        job_progress_uid = f"oseh_jp_{secrets.token_urlsafe(16)}"
        res = await start_upload(
            itgs,
            file_size=args.file_size,
            success_job_name=args.job,
            success_job_kwargs={
                "uploaded_by_user_sub": auth_result.result.sub,
                "job_progress_uid": job_progress_uid,
                **(
                    {}
                    if args.dynamic_size is None
                    else {"dynamic_size": args.dynamic_size.model_dump()}
                ),
            },
            failure_job_name="runners.delete_file_upload",
            failure_job_kwargs=dict(),
            job_progress_uid=job_progress_uid,
        )
        return Response(
            content=res.__pydantic_serializer__.to_json(res),
            headers={"Content-Type": "application/json; charset=utf-8"},
            status_code=201,
        )
