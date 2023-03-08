from pydantic import BaseModel, Field
from interactive_prompts.models.prompt import Prompt


class ExternalInteractivePrompt(BaseModel):
    uid: str = Field(
        description="The primary stable external identifier of the interactive prompt"
    )
    jwt: str = Field(
        description="A JWT that can be used to interact with the prompt when combined with the uid and session uid"
    )
    session_uid: str = Field(
        description="The UID of the session within the prompt, for event endpoints"
    )
    prompt: Prompt = Field(
        description="How the prompt functions (how to display, what types of interactions are possible, etc.)"
    )
    duration_seconds: int = Field(
        description="How long the prompt should be displayed for"
    )
