def shared_screen_configurable_trigger_001(
    description: str, /, *, include_default: bool = True
):
    return {
        "type": "object",
        "description": description,
        "example": {"type": "pop"},
        **({"default": {"type": "pop"}} if include_default else {}),
        "x-enum-discriminator": "type",
        "oneOf": [
            {
                "type": "object",
                "description": "Just pop the screen without any trigger",
                "example": {"type": "pop"},
                "required": ["type"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["pop"],
                        "description": "Just pop the screen without any trigger",
                        "example": "pop",
                    }
                },
            },
            {
                "type": "object",
                "description": "Trigger a client flow, optionally overriding the endpoint and client parameters",
                "example": {"type": "flow", "flow": "empty"},
                "required": ["type", "flow"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["flow"],
                        "description": "Trigger a client flow, optionally overriding the endpoint and client parameters",
                        "example": "flow",
                    },
                    "flow": {
                        "type": "string",
                        "format": "flow_slug",
                        "description": "The client flow to trigger",
                        "example": "empty",
                    },
                    "endpoint": {
                        "type": "string",
                        "nullable": True,
                        "default": None,
                        "description": "The endpoint to use for the trigger",
                        "example": None,
                    },
                    "parameters": {
                        "type": "object",
                        "nullable": True,
                        "default": None,
                        "description": "The client parameters to use for the trigger; null is treated like an empty object",
                        "example": {"key": "value"},
                    },
                },
            },
        ],
    }
