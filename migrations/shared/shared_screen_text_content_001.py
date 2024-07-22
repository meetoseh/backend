SHARED_SCREEN_TEXT_CONTENT_SCHEMA_V001 = {
    "type": "object",
    "description": "The text content to display",
    "example": {
        "type": "screen-text-content",
        "version": 1,
        "parts": [
            {"type": "header", "value": "Hello, world!"},
            {"type": "spacer", "pixels": 12},
            {"type": "body", "value": "This is a test."},
        ],
    },
    "required": ["type", "version", "parts"],
    "properties": {
        "type": {
            "type": "string",
            "enum": ["screen-text-content"],
            "example": "screen-text-content",
            "description": "Reserved for future use. Always screen-text-content",
        },
        "version": {
            "type": "integer",
            "format": "int32",
            "example": 1,
            "description": "Reserved for future use. Always 1",
        },
        "parts": {
            "type": "array",
            "description": "The parts of the text content, laid out vertically",
            "example": [
                {"type": "header", "value": "Hello, world!"},
                {"type": "spacer", "pixels": 12},
                {"type": "body", "value": "This is a test."},
            ],
            "items": {
                "type": "object",
                "description": "A part of the text content",
                "example": {"type": "header", "value": "Hello, world!"},
                "x-enum-discriminator": "type",
                "oneOf": [
                    {
                        "type": "object",
                        "description": "A header message (prominent text)",
                        "example": {"type": "header", "value": "Hello, world!"},
                        "required": ["type", "value"],
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["header"],
                                "example": "header",
                                "description": "A header message (prominent text)",
                            },
                            "value": {
                                "type": "string",
                                "example": "Hello, world!",
                                "description": "The header text to display",
                            },
                        },
                    },
                    {
                        "type": "object",
                        "description": "A body message (normal text)",
                        "example": {"type": "body", "value": "This is a test."},
                        "required": ["type", "value"],
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["body"],
                                "example": "body",
                                "description": "A body message (normal text)",
                            },
                            "value": {
                                "type": "string",
                                "example": "This is a test.",
                                "description": "The body text to display",
                            },
                        },
                    },
                    {
                        "type": "object",
                        "description": "A spacer to add vertical space",
                        "example": {"type": "spacer", "pixels": 12},
                        "required": ["type", "pixels"],
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["spacer"],
                                "example": "spacer",
                                "description": "A spacer to add vertical space",
                            },
                            "pixels": {
                                "type": "integer",
                                "format": "int32",
                                "example": 12,
                                "description": "The number of pixels to add",
                            },
                        },
                    },
                    {
                        "type": "object",
                        "description": "A checkmark and message in one line",
                        "example": {"type": "check", "message": "Something is done."},
                        "required": ["type", "message"],
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["check"],
                                "example": "check",
                                "description": "A checkmark and message in one line",
                            },
                            "message": {
                                "type": "string",
                                "example": "Something is done.",
                                "description": "The message to display after the check",
                            },
                        },
                    },
                ],
            },
        },
    },
}
