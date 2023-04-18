from itgs import Itgs


async def on_entering_lobby(
    itgs: Itgs, user_sub: str, journey_uid: str, action: str = "entering a lobby"
) -> None:
    """Performs any necessary triggers for the user with the given sub
    entering the lobby for the journey with the given uid. This should
    be triggered when the journey ref is returned to the client.

    Arg:
        itgs (Itgs): The integrations to (re)use
        user_sub (str): The sub of the user entering the lobby
        journey_uid (str): The uid of the journey the user is entering
        action (str): The action the user is performing, typically "entering a lobby".
          However, different actions can often reuse the exact same message if it's
          the same idea of "entering", but entering a lobby doesn't make sense -- e.g,
          for courses, "taking the next class in Dylan's course" is a better action
    """
    jobs = await itgs.jobs()
    await jobs.enqueue(
        "runners.notify_on_entering_lobby",
        user_sub=user_sub,
        journey_uid=journey_uid,
        action=action,
    )
