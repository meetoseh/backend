from typing import List


def shared_screen_exact_dynamic_image_001(path_to_me: List[str]):
    return {
        "type": "object",
        "required": ["image", "width", "height"],
        "example": {
            "image": "oseh_if_utnIdo3z0V65FnFSc-Rs-g",
            "width": 200,
            "height": 200,
        },
        "properties": {
            "image": {
                "type": "string",
                "format": "image_uid",
                "example": "oseh_if_utnIdo3z0V65FnFSc-Rs-g",
                "description": "The image to render; must be at least 3x the logical size.",
                "x-processor": {
                    "job": "runners.screens.exact_dynamic_process_image",
                    "list": "exact_dynamic",
                },
                "x-dynamic-size": {
                    "width": [*path_to_me, "width"],
                    "height": [*path_to_me, "height"],
                },
            },
            "width": {
                "type": "integer",
                "description": "The logical width of the image in pixels.",
                "example": 200,
                "minimum": 1,
                "maximum": 390 - 48,
                "multipleOf": 2,
            },
            "height": {
                "type": "integer",
                "description": "The logical height of the image in pixels.",
                "example": 200,
                "minimum": 1,
                "maximum": 400,
                "multipleOf": 2,
            },
        },
    }
