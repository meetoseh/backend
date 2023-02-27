"""This migration removes journey background images which were too small, swapping
them with a default image. Specifically, this is adding support for 13.3' macs with
a native resolution of 2560x1600
"""
from typing import List, Optional, Tuple
from daily_events.lib.read_one_external import evict_external_daily_event
from itgs import Itgs
from journeys.events.helper import purge_journey_meta
from journeys.lib.read_one_external import evict_external_journey
import socket

min_width = 2560
min_height = 2745


async def up(itgs: Itgs) -> None:
    conn = await itgs.conn()
    cursor = conn.cursor("weak")

    response = await cursor.execute(
        """
        SELECT 
            journey_background_images.uid,
            orig.uid,
            blurred.uid,
            darkened.uid
        FROM journey_background_images, image_files AS orig, image_files AS blurred, image_files AS darkened
        WHERE
            EXISTS (
                SELECT 1 FROM image_files
                WHERE image_files.id = journey_background_images.image_file_id
                  AND (image_files.original_width < ? OR image_files.original_height < ?)
            )
            AND orig.id = journey_background_images.image_file_id
            AND blurred.id = journey_background_images.blurred_image_file_id
            AND darkened.id = journey_background_images.darkened_image_file_id
        """,
        (min_width, min_height),
    )
    if not response.results:
        return

    uids: List[Tuple[str, str, str, str]] = response.results

    response = await cursor.execute(
        "SELECT journey_background_images.uid FROM journey_background_images, image_files "
        "ORDER BY image_files.original_width DESC, image_files.original_height DESC "
        "LIMIT 1"
    )
    if not response.results:
        return

    jobs = await itgs.jobs()
    default_uid = response.results[0][0]
    for (uid, *image_uids) in uids:
        response = await cursor.execute(
            """
            SELECT uid FROM journeys
            WHERE
                EXISTS (
                    SELECT 1 FROM journey_background_images
                    WHERE journey_background_images.uid = ?
                        AND (
                            journeys.background_image_file_id = journey_background_images.image_file_id
                            OR journeys.blurred_background_image_file_id = journey_background_images.blurred_image_file_id
                            OR journeys.darkened_background_image_file_id = journey_background_images.darkened_image_file_id
                        )
                )
            """,
            (uid,),
        )
        if not response.results:
            continue
        updated_journey_uids = [row[0] for row in response.results]
        response = await cursor.execute(
            """
            UPDATE journeys
            SET
                background_image_file_id = bknd.image_file_id,
                blurred_background_image_file_id = bknd.blurred_image_file_id,
                darkened_background_image_file_id = bknd.darkened_image_file_id
            FROM journey_background_images bknd
            WHERE
                EXISTS (
                    SELECT 1 FROM journey_background_images
                    WHERE journey_background_images.uid = ?
                        AND (
                            journeys.background_image_file_id = journey_background_images.image_file_id
                            OR journeys.blurred_background_image_file_id = journey_background_images.blurred_image_file_id
                            OR journeys.darkened_background_image_file_id = journey_background_images.darkened_image_file_id
                        )
                )
                AND bknd.uid = ?
            """,
            (uid, default_uid),
        )
        if response.rows_affected != len(updated_journey_uids):
            slack = await itgs.slack()
            await slack.send_web_error_message(
                f"{socket.gethostname()} Failed to update journeys with background image {uid} to use default background image {default_uid}; "
                f"expected to update {len(updated_journey_uids)} journeys, but only updated {response.rows_affected=}",
                "0019 migration issue requires manual intervention",
            )

        for updated_uid in updated_journey_uids:
            await purge_journey_meta(itgs, updated_uid)
            await evict_external_journey(itgs, uid=updated_uid)
            response = await cursor.execute(
                """
                SELECT
                    uid
                FROM daily_events
                WHERE
                    EXISTS (
                        SELECT 1 FROM daily_event_journeys
                        WHERE daily_event_journeys.daily_event_id = daily_events.id
                        AND EXISTS (
                            SELECT 1 FROM journeys
                            WHERE journeys.id = daily_event_journeys.journey_id
                            AND journeys.uid = ?
                        )
                    )
                """,
                (updated_uid,),
            )
            daily_event_uid: Optional[str] = (
                response.results[0][0] if response.results else None
            )
            if daily_event_uid:
                await evict_external_daily_event(itgs, uid=daily_event_uid)

            await jobs.enqueue(
                "runners.process_journey_video_sample", journey_uid=updated_uid
            )
            await jobs.enqueue("runners.process_journey_video", journey_uid=updated_uid)

        for img_uid in image_uids:
            await jobs.enqueue("runners.delete_image_file", uid=img_uid)

    await jobs.enqueue("runners.redo_journey_background_images")
