from itgs import Itgs


async def up(itgs: Itgs):
    conn = await itgs.conn()
    cursor = conn.cursor()

    await cursor.executemany2(
        (
            """
CREATE TABLE scratch (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL
)
            """,
            """
CREATE TABLE client_screens (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    schema TEXT NOT NULL,
    flags INTEGER NOT NULL
)
            """,
            """
CREATE TABLE client_flows (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NULL,
    description TEXT NULL,
    client_schema TEXT NOT NULL,
    server_schema TEXT NOT NULL,
    replaces BOOLEAN NOT NULL,
    screens TEXT NOT NULL,
    flags INTEGER NOT NULL,
    created_at REAL NOT NULL
)
            """,
            "CREATE INDEX client_flows_created_at_idx ON client_flows (created_at)",
            """
CREATE TABLE client_flow_images (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    list_slug TEXT NOT NULL,
    image_file_id INTEGER NOT NULL REFERENCES image_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    original_sha512 TEXT NOT NULL,
    uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    last_uploaded_at REAL NOT NULL
)
            """,
            "CREATE UNIQUE INDEX client_flow_images_image_file_list_slug_idx  ON client_flow_images(image_file_id, list_slug)",
            "CREATE UNIQUE INDEX client_flow_images_original_sha512_list_slug_idx ON client_flow_images(original_sha512, list_slug)",
            "CREATE INDEX client_flow_images_uploaded_by_user_id_idx ON client_flow_images(uploaded_by_user_id)",
            "CREATE INDEX client_flow_images_list_slug_uploaded_at_idx ON client_flow_images(list_slug, last_uploaded_at)",
            """
CREATE TABLE client_flow_content_files (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    list_slug TEXT NOT NULL,
    content_file_id INTEGER NOT NULL REFERENCES content_files(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    original_sha512 TEXT NOT NULL,
    uploaded_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    last_uploaded_at REAL NOT NULL
)
            """,
            "CREATE UNIQUE INDEX client_flow_content_files_content_list_slug_idx ON client_flow_content_files(content_file_id, list_slug)",
            "CREATE UNIQUE INDEX client_flow_content_files_original_sha512_list_slug_idx ON client_flow_content_files(original_sha512, list_slug)",
            "CREATE INDEX client_flow_content_files_uploaded_by_user_id_idx ON client_flow_content_files(uploaded_by_user_id)",
            "CREATE INDEX client_flow_content_files_list_slug_uploaded_at_idx ON client_flow_content_files(list_slug, last_uploaded_at)",
            """
CREATE TABLE user_client_screens (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    outer_counter INTEGER NOT NULL,
    inner_counter INTEGER NOT NULL,
    client_flow_id INTEGER NULL REFERENCES client_flows(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    client_screen_id INTEGER NOT NULL REFERENCES client_screens(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    flow_client_parameters TEXT NOT NULL,
    flow_server_parameters TEXT NOT NULL,
    screen TEXT NOT NULL,
    added_at REAL NOT NULL
)
            """,
            "CREATE UNIQUE INDEX user_client_screens_user_id_outer_counter_inner_counter_idx ON user_client_screens(user_id, outer_counter, inner_counter)",
            "CREATE INDEX user_client_screens_client_flow_id_idx ON user_client_screens(client_flow_id)",
            "CREATE INDEX user_client_screens_client_screen_id_idx ON user_client_screens(client_screen_id)",
            "CREATE INDEX user_client_screens_added_at_idx ON user_client_screens(added_at)",
            """
CREATE TABLE user_client_screens_log (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    platform TEXT NOT NULL,
    visitor_id INTEGER NULL REFERENCES visitors(id) ON DELETE SET NULL ON UPDATE RESTRICT,
    screen TEXT NOT NULL,
    created_at REAL NOT NULL
)
            """,
            "CREATE INDEX user_client_screens_log_user_id_created_at_idx ON user_client_screens_log(user_id, created_at)",
            """
CREATE TABLE user_client_screen_actions_log (
    id INTEGER PRIMARY KEY,
    uid TEXT UNIQUE NOT NULL,
    user_client_screen_log_id INTEGER NOT NULL REFERENCES user_client_screens_log(id) ON DELETE CASCADE ON UPDATE RESTRICT,
    event TEXT NOT NULL,
    created_at REAL NOT NULL
)
            """,
            "CREATE INDEX user_client_screen_actions_log_user_client_screen_log_id_created_at_idx ON user_client_screen_actions_log(user_client_screen_log_id, created_at)",
            """
CREATE TABLE client_flow_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    triggered INTEGER NOT NULL,
    triggered_breakdown TEXT NOT NULL,
    replaced INTEGER NOT NULL,
    replaced_breakdown TEXT NOT NULL
)
            """,
            """
CREATE TABLE client_screen_stats (
    id INTEGER PRIMARY KEY,
    retrieved_for TEXT UNIQUE NOT NULL,
    retrieved_at REAL NOT NULL,
    queued INTEGER NOT NULL,
    queued_breakdown TEXT NOT NULL,
    peeked INTEGER NOT NULL,
    peeked_breakdown TEXT NOT NULL,
    popped INTEGER NOT NULL,
    popped_breakdown TEXT NOT NULL,
    traced INTEGER NOT NULL,
    traced_breakdown TEXT NOT NULL
)
            """,
        ),
        transaction=False,
    )
