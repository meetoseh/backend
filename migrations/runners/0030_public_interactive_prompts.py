from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        """
        CREATE TABLE public_interactive_prompts (
            id INTEGER PRIMARY KEY,
            uid TEXT UNIQUE NOT NULL,
            interactive_prompt_id INTEGER UNIQUE NOT NULL REFERENCES interactive_prompts(id) ON DELETE CASCADE,
            public_identifier TEXT NOT NULL,
            version INTEGER NOT NULL
        )
        """
    )
    await cursor.execute(
        "CREATE INDEX public_interactive_prompts_public_identifier_version_idx ON public_interactive_prompts(public_identifier, version)"
    )
