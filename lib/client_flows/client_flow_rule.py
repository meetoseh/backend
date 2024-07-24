from pydantic import BaseModel, Field, TypeAdapter
from typing import Literal, Union, List, cast

from lib.client_flows.client_flow_predicate import ClientFlowPredicate


class ClientFlowEffectReplaceParametersCopy(BaseModel):
    type: Literal["copy"] = Field(
        description="Discriminatory union field; indicates copy as-is"
    )


class ClientFlowEffectReplaceParametersOmit(BaseModel):
    type: Literal["omit"] = Field(
        description="Discriminatory union field; indicates the key should be omitted"
    )


ClientFlowEffectReplaceParameters = Union[
    ClientFlowEffectReplaceParametersCopy,
    ClientFlowEffectReplaceParametersOmit,
]


class ClientFlowEffectReplace(BaseModel):
    type: Literal["replace"] = Field(
        description="Discriminatory union field; indicates the flow should be replaced at trigger time"
    )
    slug: str = Field(description="The slug of the flow to replace this flow with")
    client_parameters: ClientFlowEffectReplaceParameters = Field(
        description="What to do with the client parameters"
    )
    server_parameters: ClientFlowEffectReplaceParameters = Field(
        description="What to do with the server parameters"
    )


class ClientFlowEffectSkip(BaseModel):
    type: Literal["skip"] = Field(
        description="Discriminatory union field; shortcut for replace with skip and omit parameters"
    )


ClientFlowEffect = Union[ClientFlowEffectReplace, ClientFlowEffectSkip]


class ClientFlowRule(BaseModel):
    """A rule within the rules list of a client flow; apply the effect if the condition is met"""

    effect: ClientFlowEffect = Field(
        description="The effect to apply if the condition is met"
    )
    condition: ClientFlowPredicate = Field(description="The condition to check")


ClientFlowRules = List[ClientFlowRule]
client_flow_rules_adapter = cast(
    TypeAdapter[ClientFlowRules], TypeAdapter(ClientFlowRules)
)
