from typing import List, Optional, Protocol, Union

from lib.client_flows.helper import pretty_path
from lib.client_flows.special_index import SpecialIndex


class SchemaVisitor(Protocol):
    def on_item(
        self,
        item: dict,
        /,
        *,
        schema_path_from_root: List[Union[str, int]],
        value_path_from_root: List[Union[str, SpecialIndex]],
        inverted: bool,
    ) -> None:
        """Called for every OpenAPI 3.0.3 schema object within the given OpenAPI 3.0.3 schema

        Args:
            item (dict): the schema object
            schema_path_from_root (List[Union[str, int]]): the path from the root schema object to the current schema object
            value_path_from_root (List[Union[str, SpecialIndex]]): if you were walking an object that met this schema
                definition, the path within that object to the value that meets this schema
            inverted (bool): whether the schema object is negated by a "not" object somewhere in the path.
                Two nots is still inverted
        """
        ...


def walk_schema(
    schema: dict,
    visitor: SchemaVisitor,
    /,
    *,
    schema_path_from_root: Optional[List[Union[str, int]]] = None,
    value_path_from_root: Optional[List[Union[str, SpecialIndex]]] = None,
    inverted: bool = False,
) -> None:
    """Visits every OpenAPI 3.0.3 schema object within the given OpenAPI 3.0.3 schema
    object.

    Requires "type" on every schema object (to help catch if we're visiting the wrong objects)
    """
    if schema_path_from_root is None:
        schema_path_from_root = []
    if value_path_from_root is None:
        value_path_from_root = []

    if not isinstance(schema, dict):
        raise ValueError(
            f"cannot walk: invalid schema at {pretty_path(schema_path_from_root)}"
        )

    schema_type = schema.get("type")
    if schema_type is None:
        raise ValueError(
            f"cannot walk: missing type at {pretty_path(schema_path_from_root)}"
        )

    if not isinstance(schema_type, str):
        raise ValueError(
            f"cannot walk: invalid type at {pretty_path(schema_path_from_root)}"
        )

    visitor.on_item(
        schema,
        schema_path_from_root=schema_path_from_root,
        value_path_from_root=value_path_from_root,
        inverted=inverted,
    )

    all_of = schema.get("allOf")
    if all_of is not None:
        if not isinstance(all_of, list):
            raise ValueError(
                f"cannot walk: invalid allOf at {pretty_path(schema_path_from_root)}"
            )

        for index, item in enumerate(all_of):
            walk_schema(
                item,
                visitor,
                schema_path_from_root=schema_path_from_root + ["allOf", index],
                value_path_from_root=value_path_from_root,
                inverted=inverted,
            )

    any_of = schema.get("anyOf")
    if any_of is not None:
        if not isinstance(any_of, list):
            raise ValueError(
                f"cannot walk: invalid anyOf at {pretty_path(schema_path_from_root)}"
            )

        for index, item in enumerate(any_of):
            walk_schema(
                item,
                visitor,
                schema_path_from_root=schema_path_from_root + ["anyOf", index],
                value_path_from_root=value_path_from_root,
                inverted=inverted,
            )

    one_of = schema.get("oneOf")
    if one_of is not None:
        if not isinstance(one_of, list):
            raise ValueError(
                f"cannot walk: invalid oneOf at {pretty_path(schema_path_from_root)}"
            )

        for index, item in enumerate(one_of):
            walk_schema(
                item,
                visitor,
                schema_path_from_root=schema_path_from_root + ["oneOf", index],
                value_path_from_root=value_path_from_root,
                inverted=inverted,
            )

    not_ = schema.get("not")
    if not_ is not None:
        walk_schema(
            not_,
            visitor,
            schema_path_from_root=schema_path_from_root + ["not"],
            value_path_from_root=value_path_from_root,
            inverted=True,
        )

    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, dict):
            raise ValueError(
                f"cannot walk: invalid properties at {pretty_path(schema_path_from_root)}"
            )

        for key, item in properties.items():
            walk_schema(
                item,
                visitor,
                schema_path_from_root=schema_path_from_root + ["properties", key],
                value_path_from_root=value_path_from_root + [key],
                inverted=inverted,
            )

    items = schema.get("items")
    if items is not None:
        walk_schema(
            items,
            visitor,
            schema_path_from_root=schema_path_from_root + ["items"],
            value_path_from_root=value_path_from_root + [SpecialIndex.ARRAY_INDEX],
            inverted=inverted,
        )

    additional_items = schema.get("additionalItems")
    if additional_items is not None:
        walk_schema(
            additional_items,
            visitor,
            schema_path_from_root=schema_path_from_root + ["additionalItems"],
            value_path_from_root=value_path_from_root + [SpecialIndex.ARRAY_INDEX],
            inverted=inverted,
        )

    pattern_properties = schema.get("patternProperties")
    if pattern_properties is not None:
        if not isinstance(pattern_properties, dict):
            raise ValueError(
                f"cannot walk: invalid schema_path_from_root at {pretty_path(schema_path_from_root)}"
            )

        for key, item in pattern_properties.items():
            walk_schema(
                item,
                visitor,
                schema_path_from_root=schema_path_from_root
                + ["patternProperties", key],
                value_path_from_root=value_path_from_root + [key],
                inverted=inverted,
            )

    additional_properties = schema.get("additionalProperties")
    if (
        additional_properties is not None
        and additional_properties is not False
        and additional_properties is not True
    ):
        walk_schema(
            additional_properties,
            visitor,
            schema_path_from_root=schema_path_from_root + ["additionalProperties"],
            value_path_from_root=value_path_from_root + ["*"],
            inverted=inverted,
        )
