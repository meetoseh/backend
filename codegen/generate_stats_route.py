import argparse
from dataclasses import dataclass
import os
from typing import Dict, List, Set, TextIO, Tuple
import re


@dataclass
class GenerateStatsRouteArgs:
    database_docs_path: str
    """The path to the documentation file that will be used to generate the routes,
    e.g., docs/db/stats/siwo_authorize_stats.md
    """

    route_path: str
    """The path where the route file should be stored, e.g.,
    admin/siwo/routes/authorize_stats.py
    """

    redis_key_prefix: str
    """The prefix for redis keys, e.g, stats:sign_in_with_oseh:authorize"""

    diskcache_key_prefix: str
    """The prefix for diskcache keys, e.g., daily_siwo_authorize"""

    num_partial_days: int
    """The number of days to include in the partial response, e.g., 2"""

    no_breakdown_docs: bool
    """True to prevent breakdown docs from being generated as we prefer to
    keep them internal only
    """


def main():
    parser = argparse.ArgumentParser(description="Generate a route file for stats")
    parser.add_argument(
        "--database_docs_path",
        type=str,
        help="The path to the documentation file that will be used to generate the routes",
        required=True,
    )
    parser.add_argument(
        "--route_path",
        type=str,
        help="The path where the route file should be stored",
        required=True,
    )
    parser.add_argument(
        "--redis_key_prefix",
        type=str,
        help="The prefix for redis keys",
        required=True,
    )
    parser.add_argument(
        "--diskcache_key_prefix",
        type=str,
        help="The prefix for diskcache keys",
        required=True,
    )
    parser.add_argument(
        "--num_partial_days",
        type=int,
        help="The number of days to include in the partial response",
        default=2,
    )
    parser.add_argument(
        "--no_breakdown_docs",
        action="store_true",
        help="True to prevent breakdown docs from being generated as we prefer to keep them internal only",
    )
    args = parser.parse_args()
    generate_stats_route(
        GenerateStatsRouteArgs(
            database_docs_path=args.database_docs_path,
            route_path=args.route_path,
            redis_key_prefix=args.redis_key_prefix,
            diskcache_key_prefix=args.diskcache_key_prefix,
            num_partial_days=args.num_partial_days,
            no_breakdown_docs=args.no_breakdown_docs,
        )
    )


def generate_stats_route(args: GenerateStatsRouteArgs) -> None:
    print(f"{args=}")
    verify_redis_keys_documented(args)
    verify_diskcache_keys_documented(args)
    parsed = parse_database_documentation_file(args, args.database_docs_path)
    print(f"{parsed=}")

    camel_table_name = "".join(
        word.capitalize() for word in parsed.table_name.split("_")
    )
    spaced_table_name = " ".join(word for word in parsed.table_name.split("_"))

    if os.path.exists(args.route_path):
        print(f"File {args.route_path} already exists, exiting")
        return

    with open(args.route_path, "w") as f:
        print(
            f"""import asyncio
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field
from typing import Annotated, Dict, List, Optional
import admin.lib.read_daily_stats as read_daily_stats
from models import STANDARD_ERRORS_BY_CODE
from lifespan import lifespan_handler


router = APIRouter()

class {camel_table_name}(BaseModel):
    labels: List[str] = Field(description="index-correspondant labels for all lists")""",
            file=f,
        )
        for field_name in parsed.fields_order:
            if field_name in parsed.basic_fields:
                field = parsed.basic_fields[field_name]
                print(
                    f"    {field.name}: List[int] = Field(description=", file=f, end=""
                )
                for line in field.docs.splitlines(keepends=True):
                    print(f'        "{escape_pystr(line)}"', file=f)
                print("    )", file=f)
            else:
                field = parsed.fancy_fields[field_name]
                print(
                    f"    {field.name}: List[int] = Field(description=", file=f, end=""
                )
                for line in field.docs.splitlines(keepends=True):
                    print(f'        "{escape_pystr(line)}"', file=f)
                print("    )", file=f)

                breakdown_type_str = (
                    "Dict[str, List[int]]"
                    if field.name not in parsed.sparse_fancy_fields
                    else "Dict[str, Dict[int, int]]"
                )
                print(
                    f"    {field.name}_breakdown: {breakdown_type_str} = Field(",
                    file=f,
                    end="",
                )
                for idx, line in enumerate(
                    field.breakdown_docs.splitlines(keepends=True)
                ):
                    if idx == 0:
                        print("description=", file=f, end="")
                    print(f'        "{escape_pystr(line)}"', file=f)
                print("    )", file=f)

        print(f"\nclass Partial{camel_table_name}Item(BaseModel):", file=f)
        for field_name in parsed.fields_order:
            print(f"    {field_name}: int = Field(0)", file=f)
            if field_name in parsed.fancy_fields:
                print(
                    f"    {field_name}_breakdown: Dict[str, int] = Field(default_factory=dict)",
                    file=f,
                )
        print("", file=f)
        print(f"class Partial{camel_table_name}(BaseModel):", file=f)
        for key in ["today", "yesterday", "two_days_ago"][: args.num_partial_days]:
            print(
                f"    {key}: Partial{camel_table_name}Item = Field(default_factory=lambda: Partial{camel_table_name}Item.model_validate({{}}))",
                file=f,
            )

        simple_fields_list = ",".join(
            f'"{f}"' for f in parsed.fields_order if f in parsed.basic_fields
        )
        fancy_fields_list = ",".join(
            f'"{f}"' for f in parsed.fancy_fields if f in parsed.fancy_fields
        )
        sparse_fancy_fields_list = ",".join(
            f'"{f}"' for f in parsed.sparse_fancy_fields
        )
        print(
            f'''
route = read_daily_stats.create_daily_stats_route(
    read_daily_stats.ReadDailyStatsRouteArgs(
        table_name="{parsed.table_name}",
        basic_data_redis_key=lambda unix_date: f"{args.redis_key_prefix}:daily:{{unix_date}}".encode(
            "ascii"
        ),
        extra_data_redis_key=lambda unix_date, event: f"{args.redis_key_prefix}:daily:{{unix_date}}:extra:{{event}}".encode(
            "ascii"
        ),
        earliest_data_redis_key=b"{args.redis_key_prefix}:daily:earliest",
        pubsub_redis_key=b"ps:{args.redis_key_prefix}:daily",
        compressed_response_local_cache_key=lambda start_unix_date, end_unix_date: f"{args.diskcache_key_prefix}:{{start_unix_date}}:{{end_unix_date}}".encode(
            "ascii"
        ),
        simple_fields=[
            {simple_fields_list}
        ],
        fancy_fields=[
            {fancy_fields_list}
        ],
        sparse_fancy_fields=[
            {sparse_fancy_fields_list}
        ],
        response_model={camel_table_name},
        partial_response_model=Partial{camel_table_name},
    )
)


@router.get(
    "/{parsed.table_name}",
    response_model={camel_table_name},
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_{parsed.table_name}(authorization: Annotated[Optional[str], Header()] = None):
    """Reads {spaced_table_name} from the database for the preceeding 90
    days, ending {'yesterday' if args.num_partial_days == 1 else 'before yesterday' if args.num_partial_days == 2 else 'two days before yesterday'}. This endpoint is aggressively
    cached, thus it's not generally necessary for the frontend to reduce
    requests beyond respecting the cache control headers.

    Requires standard authorization for an admin user.
    """
    return await route.handler(authorization)


@router.get(
    "/partial_{parsed.table_name}",
    response_model=Partial{camel_table_name},
    responses=STANDARD_ERRORS_BY_CODE,
)
async def read_partial_{parsed.table_name}(
    authorization: Optional[str] = Header(None),
):
    """Reads the {spaced_table_name} that may still change. This endpoint
    is not cached in order to give the latest result.

    Requires standard authorization for an admin user.
    """
    return await route.partial_handler(authorization)


@lifespan_handler
async def register_background_tasks():
    task = asyncio.create_task(route.background_task())
    yield
''',
            file=f,
        )


def verify_redis_keys_documented(args: GenerateStatsRouteArgs):
    daily_key = f"{args.redis_key_prefix}:daily:{{unix_date}}"
    extra_key = f"{args.redis_key_prefix}:daily:{{unix_date}}:extra:{{event}}"
    earliest_key = f"{args.redis_key_prefix}:daily:earliest"
    pubsub_key = f"ps:{args.redis_key_prefix}:daily"

    missing_keys = [
        f"- `{k}`" for k in [daily_key, extra_key, earliest_key, pubsub_key]
    ]

    with open("docs/redis/keys.md") as f:
        for line in f:
            found_key = None
            for key in missing_keys:
                if line.startswith(key):
                    found_key = key
                    break
            if found_key:
                missing_keys.remove(found_key)

    assert not missing_keys, f"Missing keys in redis/keys.md: {missing_keys}"


def verify_diskcache_keys_documented(args: GenerateStatsRouteArgs):
    expected_prefix = (
        f"- `{args.diskcache_key_prefix}:{{start_unix_date}}:{{end_unix_date}}"
    )

    with open("docs/diskcache/keys.md") as f:
        for line in f:
            if line.startswith(expected_prefix):
                return

    assert False, f"Missing key in diskcache/keys.md: {expected_prefix}"


@dataclass
class Field:
    name: str
    docs: str


@dataclass
class FancyField:
    name: str
    docs: str
    breakdown_docs: str


@dataclass
class ParsedDatabaseDocumentationFile:
    table_name: str
    basic_fields: Dict[str, Field]
    fancy_fields: Dict[str, FancyField]
    sparse_fancy_fields: Set[str]
    fields_order: List[str]


def parse_database_documentation_file(
    args: GenerateStatsRouteArgs, path: str
) -> ParsedDatabaseDocumentationFile:
    with open(path) as f:
        table_name = read_table_name(f)
        skip_to_fields(f)
        fields = read_fields(f)
        (
            basic_fields,
            fancy_fields,
            sparse_fancy_fields,
            fields_order,
        ) = interpret_fields(args, fields)
    return ParsedDatabaseDocumentationFile(
        table_name=table_name,
        basic_fields=basic_fields,
        fancy_fields=fancy_fields,
        sparse_fancy_fields=sparse_fancy_fields,
        fields_order=fields_order,
    )


def read_table_name(f: TextIO) -> str:
    for line in f:
        if line.startswith("# "):
            return line[2:].strip()
    raise Exception("Could not find table name")


def skip_to_fields(f: TextIO) -> None:
    for line in f:
        if line == "## Fields\n":
            return
    raise Exception("Could not find fields")


def read_fields(f: TextIO) -> List[Field]:
    line = next(f)
    fields: List[Field] = []

    while True:
        if line == "## Schema\n":
            return fields
        if not line.startswith("- `"):
            line = next(f)
            continue

        # e.g., `- `attempted`: number of times a reminder was attempted to be sent`
        name, docs = line[2:].split("`:", 1)
        name = name[1 : name.index(" ")]
        docs = docs.strip()

        line = next(f)
        while line.startswith("  "):
            docs = docs + "\n" + line.strip()
            line = next(f)

        fields.append(Field(name=name, docs=docs))


def interpret_fields(
    args: GenerateStatsRouteArgs, fields: List[Field]
) -> Tuple[Dict[str, Field], Dict[str, FancyField], Set[str], List[str]]:
    fields = [
        f for f in fields if f.name not in ("id", "retrieved_for", "retrieved_at")
    ]
    fields_by_name = dict((f.name, f) for f in fields)
    fields_order = [f.name for f in fields if not f.name.endswith("_breakdown")]
    simple_field_names = set(
        f.name for f in fields if not f.name.endswith("_breakdown")
    )

    fancy_fields: Dict[str, FancyField] = dict()
    for f in fields:
        if f.name.endswith("_breakdown"):
            real_name = f.name[: -len("_breakdown")]
            simple_field_names.remove(real_name)
            fancy_fields[real_name] = FancyField(
                name=real_name,
                docs=fields_by_name[real_name].docs,
                breakdown_docs="" if args.no_breakdown_docs else f.docs,
            )

    sparse_fancy_fields = set(
        f.name
        for f in fancy_fields.values()
        if (
            "_sparse_" in f.docs
            or "_sparse_" in fields_by_name[f"{f.name}_breakdown"].docs
        )
    )

    sparse_regex = re.compile(r"_sparse_\s*")
    for sparse_fancy_field_name in sparse_fancy_fields:
        f = fancy_fields[sparse_fancy_field_name]
        f.docs = sparse_regex.sub("", f.docs).rstrip()
        f.breakdown_docs = sparse_regex.sub("", f.breakdown_docs)
        if f.breakdown_docs:
            f.breakdown_docs += "\n\n"
        f.breakdown_docs += (
            "This field is provided in a sparse format, i.e., rather than a list\n"
            "it is presented as a json object where the keys are the stringified\n"
            "0-based index and the values are the counts. Omitted keys have a\n"
            'count of 0. Ex: `{"0": 1, "3": 2}` is the same as `[1,0,0,2,0]`\n'
            "if the length of labels is 5"
        )

    simple_fields = dict((f.name, f) for f in fields if f.name in simple_field_names)
    return simple_fields, fancy_fields, sparse_fancy_fields, fields_order


def escape_pystr(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


if __name__ == "__main__":
    main()
