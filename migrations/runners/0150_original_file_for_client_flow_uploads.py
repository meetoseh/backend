from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            "PRAGMA foreign_keys = OFF",
            "DROP INDEX client_flow_images_image_file_list_slug_idx",
            "DROP INDEX client_flow_images_original_sha512_list_slug_idx",
            "DROP INDEX client_flow_images_uploaded_by_user_id_idx",
            "DROP INDEX client_flow_images_list_slug_uploaded_at_idx",
            """
CREATE TABLE client_flow_images_new (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    list_slug TEXT NOT NULL,
    image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    original_s3_file_id INTEGER NULL REFERENCES s3_files(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    original_sha512 TEXT NOT NULL,
    uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    last_uploaded_at REAL NOT NULL
)
            """,
            """
INSERT INTO client_flow_images_new (
    id, uid, list_slug, image_file_id, original_s3_file_id, original_sha512, uploaded_by_user_id, last_uploaded_at
)
SELECT
    id, uid, list_slug, image_file_id, NULL, original_sha512, uploaded_by_user_id, last_uploaded_at
FROM client_flow_images
            """,
            "DROP TABLE client_flow_images",
            "ALTER TABLE client_flow_images_new RENAME TO client_flow_images",
            "CREATE UNIQUE INDEX client_flow_images_image_file_list_slug_idx  ON client_flow_images(image_file_id, list_slug)",
            "CREATE UNIQUE INDEX client_flow_images_original_sha512_list_slug_idx ON client_flow_images(original_sha512, list_slug)",
            "CREATE INDEX client_flow_images_original_s3_file_id_idx ON client_flow_images(original_s3_file_id)",
            "CREATE INDEX client_flow_images_uploaded_by_user_id_idx ON client_flow_images(uploaded_by_user_id)",
            "CREATE INDEX client_flow_images_list_slug_uploaded_at_idx ON client_flow_images(list_slug, last_uploaded_at)",
            "DROP INDEX client_flow_content_files_content_list_slug_idx",
            "DROP INDEX client_flow_content_files_original_sha512_list_slug_idx",
            "DROP INDEX client_flow_content_files_uploaded_by_user_id_idx",
            "DROP INDEX client_flow_content_files_list_slug_uploaded_at_idx",
            """
CREATE TABLE client_flow_content_files_new (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    list_slug TEXT NOT NULL,
    content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    original_s3_file_id INTEGER NULL REFERENCES s3_files(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    original_sha512 TEXT NOT NULL,
    uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    last_uploaded_at REAL NOT NULL
)
            """,
            """
INSERT INTO client_flow_content_files_new (
    id, uid, list_slug, content_file_id, original_s3_file_id, original_sha512, uploaded_by_user_id, last_uploaded_at
)
SELECT
    id, uid, list_slug, content_file_id, NULL, original_sha512, uploaded_by_user_id, last_uploaded_at
FROM client_flow_content_files
            """,
            "DROP TABLE client_flow_content_files",
            "ALTER TABLE client_flow_content_files_new RENAME TO client_flow_content_files",
            "CREATE UNIQUE INDEX client_flow_content_files_content_list_slug_idx ON client_flow_content_files(content_file_id, list_slug)",
            "CREATE UNIQUE INDEX client_flow_content_files_original_sha512_list_slug_idx ON client_flow_content_files(original_sha512, list_slug)",
            "CREATE INDEX client_flow_content_files_original_s3_file_id_idx ON client_flow_content_files(original_s3_file_id)",
            "CREATE INDEX client_flow_content_files_uploaded_by_user_id_idx ON client_flow_content_files(uploaded_by_user_id)",
            "CREATE INDEX client_flow_content_files_list_slug_uploaded_at_idx ON client_flow_content_files(list_slug, last_uploaded_at)",
            "PRAGMA foreign_keys = ON",
        ),
        transaction=False,
    )
