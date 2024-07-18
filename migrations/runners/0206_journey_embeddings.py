from itgs import Itgs


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
CREATE TABLE journey_embeddings(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    model TEXT NOT NULL,
    technique TEXT NOT NULL,
    journey_uid_byte_length INTEGER NOT NULL,
    embedding_byte_length INTEGER NOT NULL,
    s3_file_id INTEGER UNIQUE NOT NULL REFERENCES s3_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    sha512 TEXT NOT NULL,
    created_at REAL NOT NULL
)
            """,
            """
CREATE TABLE journey_embedding_items(
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    journey_embedding_id INTEGER NOT NULL REFERENCES journey_embeddings(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    journey_id INTEGER NULL REFERENCES journeys(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    offset INTEGER NOT NULL
)
            """,
            "CREATE UNIQUE INDEX journey_embedding_items_journey_embedding_id_journey_id_idx ON journey_embedding_items(journey_embedding_id, journey_id)",
            "CREATE INDEX journey_embedding_items_journey_id_idx ON journey_embedding_items(journey_id)",
        ),
        transaction=False,
    )
