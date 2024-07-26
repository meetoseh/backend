from pydantic import BaseModel, Field
from typing import Dict, Optional
from itgs import Itgs
from lib.sticky_random_groups import check_if_user_in_sticky_random_group
from resources.filter_item import FilterItemModel
import random


class ClientFlowPredicate(BaseModel):
    version: Optional[FilterItemModel[int]] = Field(
        None,
        description="the client-provided android version code they want to match",
    )
    time_in_queue: Optional[FilterItemModel[int]] = Field(
        None,
        description="How long the client flow screen has been in the queue. Always zero at trigger time.",
    )
    account_age: Optional[FilterItemModel[int]] = Field(
        None,
        description="How long since the users account record was created, in seconds.",
    )
    sticky_random_groups: Optional[Dict[str, FilterItemModel[int]]] = Field(
        None,
        description="For each key in this dictionary, a filter against a 1 if the user is in the sticky group with that name and 0 otherwise",
    )
    random_float: Optional[FilterItemModel[float]] = Field(
        None,
        description="A random float in the range [0, 1)",
    )


async def check_flow_predicate(
    itgs: Itgs,
    rule: ClientFlowPredicate,
    /,
    *,
    version: Optional[int],
    time_in_queue: int,
    account_age: int,
    user_sub: str,
) -> bool:
    """Checks if the given client flow rule matches the available information"""
    if rule.version is not None and not rule.version.to_result().check_constant(
        version
    ):
        return False
    if (
        rule.time_in_queue is not None
        and not rule.time_in_queue.to_result().check_constant(time_in_queue)
    ):
        return False
    if rule.account_age is not None and not rule.account_age.to_result().check_constant(
        account_age
    ):
        return False
    if rule.sticky_random_groups is not None:
        for group_name, filter_item in rule.sticky_random_groups.items():
            in_group = await check_if_user_in_sticky_random_group(
                itgs,
                user_sub=user_sub,
                group_name=group_name,
                create_if_not_exists=True,
            )
            if not filter_item.to_result().check_constant(int(in_group)):
                return False
    if rule.random_float is not None:
        val = random.random()
        if not rule.random_float.to_result().check_constant(val):
            return False
    return True
