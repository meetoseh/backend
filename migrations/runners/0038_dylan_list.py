from typing import List, Optional
from itgs import Itgs


# Used to have a klaviyo integration
class KlaviyoStub:
    async def add_profile_to_list(self, profile_id: List[str], list_id: str):
        ...


async def up(itgs: Itgs):
    """Fetches users which can from the dylan socials test and adds
    them to the corresponding klaviyo list for email retargeting
    """
    conn = await itgs.conn()
    cursor = conn.cursor("none")

    last_profile_id: Optional[str] = None
    batch_size = 50
    list_id = "RmASTZ"

    # klaviyo = await itgs.klaviyo()
    klaviyo = KlaviyoStub()

    while True:
        response = await cursor.execute(
            """
            SELECT
                DISTINCT(user_klaviyo_profiles.klaviyo_id)
            FROM users, user_klaviyo_profiles, visitor_users, visitor_utms, utms
            WHERE
                users.id = user_klaviyo_profiles.user_id
                AND visitor_users.user_id = users.id
                AND visitor_utms.visitor_id = visitor_users.visitor_id
                AND utms.id = visitor_utms.utm_id
                AND utms.utm_content = 'dylanwerner'
                AND utms.utm_source = 'instagram'
                AND (
                    ? IS NULL
                    OR user_klaviyo_profiles.klaviyo_id > ?
                )
            ORDER BY user_klaviyo_profiles.klaviyo_id ASC
            LIMIT ?
            """,
            (last_profile_id, last_profile_id, batch_size),
        )

        if not response.results:
            break

        klaviyo_ids = [row[0] for row in response.results]
        print(f"Adding {len(klaviyo_ids)} to list {list_id}... {klaviyo_ids}")

        await klaviyo.add_profile_to_list(profile_id=klaviyo_ids, list_id=list_id)

        if len(klaviyo_ids) < batch_size:
            break

        last_profile_id = klaviyo_ids[-1]
