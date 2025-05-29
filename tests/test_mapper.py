# tests/test_mapper.py

import pytest

from omnimcp.omniparser.mapper import map_omniparser_to_uielements
from omnimcp.types import Bounds

# Sample based on partial output from previous run
SAMPLE_OMNIPARSER_JSON = {
    "parsed_content_list": [
        {
            "type": "textbox",  # Example type
            "bbox": [0.1, 0.1, 0.5, 0.2],  # x_min, y_min, x_max, y_max
            "content": "Some Text",
            "confidence": 0.95,
            "attributes": {},
        },
        {
            "type": "button",
            "bbox": [0.4, 0.4, 0.6, 0.5],
            "content": "Click Me",
            # Missing confidence/attributes
        },
        {  # Example with invalid bounds
            "type": "icon",
            "bbox": [1.1, 0.1, 1.2, 0.2],
            "content": "Bad Icon",
        },
        {  # Example with missing bbox
            "type": "text",
            "content": "Text with no box",
        },
    ]
    # Add other top-level keys if they exist in real output
}

IMG_WIDTH = 1000
IMG_HEIGHT = 800


def test_mapper_basic():
    elements = map_omniparser_to_uielements(
        SAMPLE_OMNIPARSER_JSON, IMG_WIDTH, IMG_HEIGHT
    )

    # Expect 2 valid elements (textbox, button), the others skipped
    assert len(elements) == 2

    # Check first element (textbox)
    assert elements[0].id == 0
    assert elements[0].type == "textbox"
    assert elements[0].content == "Some Text"
    assert elements[0].confidence == 0.95
    # Check calculated bounds (x, y, w, h)
    expected_bounds_0: Bounds = (0.1, 0.1, 0.5 - 0.1, 0.2 - 0.1)
    assert elements[0].bounds == pytest.approx(
        expected_bounds_0
    )  # Use approx for float comparison

    # Check second element (button)
    assert elements[1].id == 1
    assert elements[1].type == "button"
    assert elements[1].content == "Click Me"
    assert elements[1].confidence == 0.0  # Default confidence
    expected_bounds_1: Bounds = (0.4, 0.4, 0.6 - 0.4, 0.5 - 0.4)
    assert elements[1].bounds == pytest.approx(expected_bounds_1)


# Add more tests for edge cases, different types, etc.
def test_mapper_empty_input():
    elements = map_omniparser_to_uielements({}, IMG_WIDTH, IMG_HEIGHT)
    assert len(elements) == 0
    elements = map_omniparser_to_uielements(
        {"parsed_content_list": []}, IMG_WIDTH, IMG_HEIGHT
    )
    assert len(elements) == 0


# TODO: more test cases
