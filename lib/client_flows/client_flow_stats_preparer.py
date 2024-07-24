from typing import Optional

from lib.client_flows.client_flow_source import ClientFlowSource
from lib.redis_stats_preparer import RedisStatsPreparer


class ClientFlowStatsPreparer:
    def __init__(self, stats: RedisStatsPreparer) -> None:
        self.stats = stats

    def incr_client_flow_stat(
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
            basic_key_format="stats:client_flows:daily:{unix_date}",
            earliest_key=b"stats:client_flows:daily:earliest",
            event_extra_format="stats:client_flows:daily:{unix_date}:extra:{event}",
        )

    def incr_triggered(
        self,
        *,
        unix_date: int,
        platform: ClientFlowSource,
        version: Optional[int],
        slug: str,
        trusted: bool,
        amt: int = 1,
    ):
        self.incr_client_flow_stat(
            unix_date=unix_date,
            event="triggered",
            event_extra=f"{platform}:{version}:{slug}:{trusted}".encode("utf-8"),
            amt=amt,
        )

    def incr_replaced(
        self,
        *,
        unix_date: int,
        platform: ClientFlowSource,
        version: Optional[int],
        screen_slug: Optional[str],
        original_flow_slug: str,
        replaced_flow_slug: str,
        amt: int = 1,
    ):
        self.incr_client_flow_stat(
            unix_date=unix_date,
            event="replaced",
            event_extra=f"{platform}:{version}:{screen_slug if screen_slug is not None else ''}:{original_flow_slug}:{replaced_flow_slug}".encode(
                "utf-8"
            ),
            amt=amt,
        )
