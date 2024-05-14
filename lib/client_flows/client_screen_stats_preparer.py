from typing import Optional

from lib.client_flows.client_flow_source import ClientFlowSource
from lib.redis_stats_preparer import RedisStatsPreparer


class ClientScreenStatsPreparer:
    def __init__(self, stats: RedisStatsPreparer) -> None:
        self.stats = stats

    def incr_client_screen_stat(
        self,
        *,
        unix_date: int,
        event: str,
        event_extra: Optional[bytes] = None,
        amt: int = 1,
    ) -> None:
        self.stats.incrby(
            unix_date=unix_date,
            event=event,
            event_extra=event_extra,
            amt=amt,
            basic_key_format="stats:client_screens:daily:{unix_date}",
            earliest_key=b"stats:client_screens:daily:earliest",
            event_extra_format="stats:client_screens:daily:{unix_date}:extra:{event}",
        )

    def incr_queued(
        self,
        *,
        unix_date: int,
        platform: ClientFlowSource,
        slug: str,
        amt: int = 1,
    ):
        self.incr_client_screen_stat(
            unix_date=unix_date,
            event="queued",
            event_extra=f"{platform}:{slug}".encode("utf-8"),
            amt=amt,
        )

    def incr_peeked(
        self,
        *,
        unix_date: int,
        platform: ClientFlowSource,
        slug: str,
        amt: int = 1,
    ):
        self.incr_client_screen_stat(
            unix_date=unix_date,
            event="peeked",
            event_extra=f"{platform}:{slug}".encode("utf-8"),
            amt=amt,
        )

    def incr_popped(
        self,
        *,
        unix_date: int,
        platform: ClientFlowSource,
        slug: str,
        amt: int = 1,
    ):
        self.incr_client_screen_stat(
            unix_date=unix_date,
            event="popped",
            event_extra=f"{platform}:{slug}".encode("utf-8"),
            amt=amt,
        )

    def incr_traced(
        self,
        *,
        unix_date: int,
        platform: ClientFlowSource,
        slug: str,
        amt: int = 1,
    ):
        self.incr_client_screen_stat(
            unix_date=unix_date,
            event="traced",
            event_extra=f"{platform}:{slug}".encode("utf-8"),
            amt=amt,
        )
