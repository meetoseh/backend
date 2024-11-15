import json
from client_flows.lib.parse_flow_screens import decode_flow_screens
from client_flows.routes.read import ClientFlow
from lib.client_flows.client_flow_rule import client_flow_rules_adapter
from itgs import Itgs

STANDARD_CLIENT_FLOW_READ_QUERY = """
SELECT
    uid,
    slug,
    name,
    description,
    client_schema,
    server_schema,
    replaces,
    screens,
    rules,
    flags,
    created_at
FROM client_flows
"""


async def parse_client_flow_read_row(itgs: Itgs, row: list) -> ClientFlow:
    """Parses a row from the standard client flow read query result"""
    return ClientFlow(
        uid=row[0],
        slug=row[1],
        name=row[2],
        description=row[3],
        client_schema=json.loads(row[4]),
        server_schema=json.loads(row[5]),
        replaces=row[6],
        screens=decode_flow_screens(row[7]),
        rules=client_flow_rules_adapter.validate_json(row[8]),
        flags=row[9],
        created_at=row[10],
    )
