from itgs import Itgs


async def on_entering_lobby(itgs: Itgs, user_sub: str, journey_uid: str) -> None:
    """Performs any necessary triggers for the user with the given sub
    entering the lobby for the journey with the given uid. This should
    be triggered when the journey ref is returned to the client.

    Arg:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The sub of the user entering the lobby
        journey_uid (str): The uid of the journey the user is entering
    """
    jobs = await itgs.jobs()
    await jobs.enqueue(
        "runners.notify_on_entering_lobby", user_sub=user_sub, journey_uid=journey_uid
    )
