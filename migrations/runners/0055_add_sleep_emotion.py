from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.execute(
        "INSERT INTO emotions (word, antonym) VALUES (?, ?)", ("sleepy", "fall asleep")
    )
