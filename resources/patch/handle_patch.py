from fastapi.responses import Response
from models import StandardErrorResponse
from typing import List, Literal, Tuple, Union
from itgs import Itgs
from rqdb.result import ResultItem
from resources.patch.exceptions import (
    ConflictException,
    PreconditionFailedException,
    SubresourceMissingException,
    UpdateFailedException,
)
from resources.patch.query import Query


async def handle_patch(
    itgs: Itgs, queries: List[Query], is_patch: bool
) -> Union[Tuple[Literal[False], Response], Tuple[Literal[True], ResultItem]]:
    """Handles the meat of most patch functions. Executes the list of queries
    in a unified transaction, then processes the results. If no errors
    occur, returns `True, result`, where `result` is the result of the last
    query, which is presumably the read for the new state of the resource. Otherwise,
    returns `False, response`, where `response` is the error response to return
    to the user.

    Args;
        itgs (Itgs): the integrations to (re)use
        queries (List[Query]): the queries to execute
        is_patch (bool): Whether an actual update query is included or not

    """
    conn = await itgs.conn()
    cursor = conn.cursor("strong" if is_patch else "none")
    response = await cursor.executeunified2(
        [q.sql for q in queries], [q.args for q in queries]
    )

    assert len(response) == len(queries), f"{response=}, {queries=}"

    precondition_errors: List[PreconditionFailedException] = []
    subresource_errors: List[SubresourceMissingException] = []
    conflict_errors: List[ConflictException] = []
    update_errors: List[UpdateFailedException] = []

    for query, result in zip(queries, response.items):
        try:
            await query.process_result(result)
        except PreconditionFailedException as e:
            precondition_errors.append(e)
        except SubresourceMissingException as e:
            subresource_errors.append(e)
        except ConflictException as e:
            conflict_errors.append(e)
        except UpdateFailedException as e:
            update_errors.append(e)

    made_changes = is_patch and not update_errors

    if precondition_errors:
        assert not made_changes, response
        return False, Response(
            content=StandardErrorResponse[str](
                type="precondition_failed",
                message=(
                    "the precondition was not met:\n- "
                    + "\n- ".join(
                        f"{e.field}: expected {e.expected!r}, but was {e.actual!r}"
                        for e in precondition_errors
                    )
                ),
            ).model_dump_json(),
            status_code=412,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

    if subresource_errors:
        assert not made_changes, response
        return False, subresource_errors[0].to_response()

    if conflict_errors:
        assert not made_changes, response
        return False, conflict_errors[0].to_response()

    if update_errors:
        return False, update_errors[0].to_response()

    read_result = response.items[-1]
    if not read_result.results:
        assert not made_changes, response
        return False, UpdateFailedException().to_response()

    return True, read_result
