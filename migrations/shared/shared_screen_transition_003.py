SHARED_SCREEN_TRANSITION_SCHEMA_V003 = {
    "type": "object",
    "description": "The animation to use",
    "example": {"type": "fade", "ms": 125},
    "default": {"type": "fade", "ms": 125},
    "x-enum-discriminator": "type",
    "oneOf": [
        {
            "type": "object",
            "description": "Fade in/out",
            "example": {"type": "fade", "ms": 125},
            "required": ["type", "ms"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["fade"],
                    "example": "fade",
                },
                "ms": {
                    "type": "integer",
                    "format": "int32",
                    "example": 125,
                    "minimum": 0,
                    "description": "Animation duration in milliseconds",
                },
            },
        },
        {
            "type": "object",
            "description": "Slide the foreground",
            "example": {"type": "swipe", "ms": 125, "direction": "to-left"},
            "required": ["type", "ms", "direction"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["swipe"],
                    "example": "swipe",
                },
                "ms": {
                    "type": "integer",
                    "format": "int32",
                    "example": 125,
                    "minimum": 0,
                    "description": "Animation duration in milliseconds",
                },
                "direction": {
                    "type": "string",
                    "enum": ["to-left", "to-right"],
                    "example": "to-left",
                },
            },
        },
        {
            "type": "object",
            "description": "Wipes a cover in front of the foreground",
            "example": {"type": "wipe", "direction": "up", "ms": 125},
            "required": ["type", "ms", "direction"],
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["wipe"],
                    "example": "wipe",
                },
                "ms": {
                    "type": "integer",
                    "format": "int32",
                    "example": 125,
                    "minimum": 0,
                    "description": "Animation duration in milliseconds",
                },
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"],
                    "example": "up",
                },
            },
        },
    ],
}
