from pydantic import BaseModel, Field
from typing import Any, Dict, List, Set, Union


class TouchPointSmsMessage(BaseModel):
    priority: int = Field(
        description="messages with lower priorities are sent first in most selection strategies"
    )
    uid: str = Field(
        description="Unique identifier for this message within the touch point"
    )
    body_format: str = Field(
        description="the format string for the body of the message, e.g., 'Hello {name}'"
    )
    body_parameters: List[str] = Field(
        description="the parameters to use for the body format string, e.g., ['name']. May use dots as separators."
    )


class TouchPointPushMessage(BaseModel):
    priority: int = Field(
        description="messages with lower priorities are sent first in most selection strategies"
    )
    uid: str = Field(
        description="Unique identifier for this message within the touch point"
    )
    title_format: str = Field(
        description="the format string for the title of the message, e.g., 'Hello {name}'"
    )
    title_parameters: List[str] = Field(
        description="the parameters to use for the title format string, e.g., ['name']. May use dots as separators."
    )
    body_format: str = Field(
        description="the format string for the body of the message, e.g., 'Hello {name}'"
    )
    body_parameters: List[str] = Field(
        description="the parameters to use for the body format string, e.g., ['name']. May use dots as separators."
    )
    channel_id: str = Field(
        description="the channel id for android push notifications, e.g., 'default'"
    )


class TouchPointTemplateParameterSubstitution(BaseModel):
    key: List[Union[str, int]] = Field(description="the path to the key to set")
    format: str = Field(
        description="the format string for the value, e.g., 'Hello {name}'"
    )
    parameters: List[str] = Field(
        description="the parameters to use for the format string, e.g., ['name']. May use dots as separators."
    )


class TouchPointEmailMessage(BaseModel):
    priority: int = Field(
        description="messages with lower priorities are sent first in most selection strategies"
    )
    uid: str = Field(
        description="Unique identifier for this message within the touch point"
    )
    subject_format: str = Field(
        description="the format string for the subject of the message, e.g., 'Hello {name}'"
    )
    subject_parameters: List[str] = Field(
        description="the parameters to use for the subject format string, e.g., ['name']. May use dots as separators."
    )
    template: str = Field(description="the slug of the template within email-templates")
    template_parameters_fixed: Dict[str, Any] = Field(
        description="non-substituted template parameters. May use dots as separators in keys."
    )
    template_parameters_substituted: List[TouchPointTemplateParameterSubstitution] = (
        Field(description="substituted template parameters")
    )


class TouchPointMessages(BaseModel):
    sms: List[TouchPointSmsMessage] = Field(
        description="the sms messages to send, in ascending priority order, ties broken according to selection strategy"
    )
    push: List[TouchPointPushMessage] = Field(
        description="the push messages to send, in ascending priority order, ties broken according to selection strategy"
    )
    email: List[TouchPointEmailMessage] = Field(
        description="the email messages to send, in ascending priority order, ties broken according to selection strategy"
    )

    def get_required_parameters(self) -> Set[str]:
        """Determines all the event parameters required to realize the messages"""
        result = set()
        for msg in self.sms:
            result.update(msg.body_parameters)
        for msg in self.push:
            result.update(msg.title_parameters)
            result.update(msg.body_parameters)
        for msg in self.email:
            result.update(msg.subject_parameters)
            for sub in msg.template_parameters_substituted:
                result.update(sub.parameters)
        return result
