from itgs import Itgs
from loguru import logger


async def up(itgs: Itgs):
    uid_to_new_sha512 = {
        "oseh_j_FLK3hxaPjP1c9ZPydN5ADA": "1ec6a8ae9f2b4007311d42538c202bdab492e01dfc1bb19bd9f715f40686705670049edac39b763bf9b606e3977e9b19772c9ca48c8fb4a54c21640934002e8c",
        "oseh_j_IQXPv14nRgJuRoZ1MxbYVg": "4388a0042c669babb6641de5ad53e5f23e519d888e077c94b08ab4ac4685d668df5e3147aa8bc4be9e2dc573c68589b411734e06eed4d9709bf3cabdd7e063d4",
        "oseh_j_hBUaWsoeuD8Je3hUeLL42w": "e1526787a12f5cec65d78608122683c3b7ea548647a384d2f0aa06bd5799a503de5c07984285928974cf55da0cb97a76ab26e2abc1b17821de36e4eaea97889a",
        "oseh_j_bd-vA4d9e42x0Pn846Rxnw": "b3b1575f48856232db4927b3661a1bb79943136c231cbfe8a169b0fce15beb8b46dcfaddbbe8e80ce0dc9b03603b8ec097634f908ad03eefa60f98291726d8ca",
        "oseh_j_tizv1PzNNmKRVp-e9M5YRg": "4a7524e2aea5b0208f6498cf18aea1ba2ddc8f1bf5ecc3b1c619886ea57b2d7eec9327435bc3f0dbbdc80f8340cb01e03c4c850cfd47c561eed07af58b2c4ce0",
        "oseh_j_pYkzcvT9JjTqqLfgJpvoBQ": "a752fada7d11b6cb631f284d01031ef849b23932e50148b5cf355ce69323bb6450e59d6cd5434b831b54f90359fd3eb474a26adde30a50be82b498727cef75db",
        "oseh_j_Wl_eauIaqGno4R4lHSk3Xg": "8441cec6cf4063530380708d0ba96386f86a07e16ea6e78462a2cba4823c2d7ed0d526dcae3a21ee69814eb4ad199a6a40be758c59baa34cd6ec7ed871f410a1",
        "oseh_j_mcQ704V1z-wX-8kw48BboA": "73f28bea630b27195997f154c13dcfcf326470847f87cb980a63d18259c13a8223034637ad9ff6d93428378b28428f20cd6e79e76201dba03b78774c9596671a",
        "oseh_j_fAnW7BvVhd0dPbd30snv8A": "ecbf970d3bd635c809d0f81c0693c44bff088426005cc099b8e6d2e7257a54ffc5579ebc58c74a698f26bb189c97048d47f764c4d246e8a99afaa5d12a744fa9",
    }
    conn = await itgs.conn()
    cursor = conn.cursor("weak")
    jobs = await itgs.jobs()

    for journey_uid, new_content_audio_sha512 in uid_to_new_sha512.items():
        response = await cursor.execute(
            """
            UPDATE journeys
            SET
                audio_content_file_id = audio_content_files.id
            FROM content_files AS audio_content_files
            WHERE
                journeys.uid = ?
                AND audio_content_files.original_sha512 = ?
            """,
            (journey_uid, new_content_audio_sha512),
        )

        if response.rows_affected is None or response.rows_affected < 1:
            logger.debug(
                f"Failed to update journey audio: {journey_uid} -> {new_content_audio_sha512}"
            )
        else:
            logger.debug(
                f"Updated journey audio: {journey_uid} -> {new_content_audio_sha512}"
            )
            await jobs.enqueue(
                "runners.process_journey_video_sample", journey_uid=journey_uid
            )
            await jobs.enqueue("runners.process_journey_video", journey_uid=journey_uid)
