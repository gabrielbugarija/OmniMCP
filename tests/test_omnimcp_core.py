# tests/test_omnimcp_core.py

"""
Tests for core OmniMCP/VisualState functionality using synthetic test images
and a mocked OmniParserClient.
"""

import pytest
from unittest.mock import patch, MagicMock  # Keep MagicMock
from PIL import Image, ImageDraw

# Imports can be at the top now
from omnimcp.omnimcp import OmniMCP, VisualState
from omnimcp.types import (
    ActionVerification,
)  # Keep Bounds if needed by other tests
from omnimcp.input import InputController


# Mock OmniParserClient for testing VisualState without real parsing
class MockOmniParserClient:
    def __init__(self, mock_data):
        self.mock_data = mock_data
        self.server_url = "mock://server"

    def parse_image(self, image: Image.Image):
        print("MockOmniParserClient: Returning mock data for parse_image call.")
        return self.mock_data

    def _check_server(self):
        print("MockOmniParserClient: Dummy server check passed.")
        return True


@pytest.fixture
def synthetic_ui_data():
    """Provides a synthetic UI image and expected element structure."""
    # Using a simple example structure for clarity
    elements_list_of_dicts = [
        {
            "bbox": [0.1, 0.1, 0.3, 0.15],
            "confidence": 1.0,
            "content": "Username",
            "type": "text_field",
        },
        {
            "bbox": [0.1, 0.3, 0.3, 0.35],
            "confidence": 1.0,
            "content": "",
            "type": "text_field",
            "attributes": {"is_password": True},
        },
        {
            "bbox": [0.1, 0.5, 0.15, 0.55],
            "confidence": 1.0,
            "content": "Remember Me",
            "type": "checkbox",
        },
        {
            "bbox": [0.4, 0.7, 0.6, 0.8],
            "confidence": 1.0,
            "content": "Login",
            "type": "button",
        },
    ]
    img = Image.new("RGB", (800, 600), color="lightgray")
    return img, {"parsed_content_list": elements_list_of_dicts}, elements_list_of_dicts


@pytest.fixture
def mock_parser_client(synthetic_ui_data):
    """Fixture to provide a MockOmniParserClient instance with mock data."""
    _, mock_json_output, _ = synthetic_ui_data
    return MockOmniParserClient(mock_data=mock_json_output)


# --- Test VisualState ---


# Test is now synchronous
def test_visual_state_parsing(synthetic_ui_data, mock_parser_client):
    """Test VisualState.update processes elements from the (mocked) parser client."""
    test_img, _, elements_expected_list_of_dicts = synthetic_ui_data

    # Patch take_screenshot used within visual_state.update
    with patch("omnimcp.omnimcp.take_screenshot", return_value=test_img):
        visual_state = VisualState(parser_client=mock_parser_client)
        assert not visual_state.elements
        assert visual_state.screen_dimensions is None

        # Call synchronous update method
        visual_state.update()

        assert visual_state.screen_dimensions == test_img.size
        assert len(visual_state.elements) == len(elements_expected_list_of_dicts)
        assert (
            visual_state.elements[0].content
            == elements_expected_list_of_dicts[0]["content"]
        )
        assert (
            visual_state.elements[0].type == elements_expected_list_of_dicts[0]["type"]
        )
        assert isinstance(visual_state.elements[0].bounds, tuple)
        assert all(isinstance(b, float) for b in visual_state.elements[0].bounds)


# Test is now synchronous
def test_element_finding(synthetic_ui_data, mock_parser_client):
    """Test VisualState.find_element locates elements using basic matching."""
    test_img, _, _ = synthetic_ui_data

    with patch("omnimcp.omnimcp.take_screenshot", return_value=test_img):
        visual_state = VisualState(parser_client=mock_parser_client)
        visual_state.update()  # Populate state

        assert len(visual_state.elements) > 0

        login_button = visual_state.find_element("login button")
        assert login_button is not None
        assert login_button.type == "button"

        username_field = visual_state.find_element("username")
        assert username_field is not None
        assert username_field.type == "text_field"

        nonexistent = visual_state.find_element("nonexistent element description")
        assert nonexistent is None


# --- Test Action Verification on OmniMCP ---


# Patch dependencies of OmniMCP.__init__ and its methods
@patch(
    "omnimcp.omnimcp.OmniParserClient"
)  # Mock the client class used by VS within OmniMCP
@patch("omnimcp.omnimcp.InputController")  # Mock the unified controller used by OmniMCP
@patch(
    "omnimcp.omnimcp.take_screenshot"
)  # Mock screenshot function called by VS update
def test_action_verification(
    mock_take_screenshot, MockInputController, MockOmniParserClientClass
):
    """
    Test the _verify_action method on an OmniMCP instance.
    """
    # Configure mocks needed for OmniMCP initialization
    mock_parser_instance = MockOmniParserClient(
        {"parsed_content_list": []}
    )  # Simple mock parser
    MockOmniParserClientClass.return_value = mock_parser_instance
    MockInputController.return_value = MagicMock(
        spec=InputController
    )  # Mock controller instance

    # --- Create OmniMCP instance ---
    # It will internally create VisualState using the mocked OmniParserClient
    # and store the mocked InputController
    mcp = OmniMCP()
    assert isinstance(mcp._controller, MagicMock)  # Verify controller mock was used
    assert isinstance(
        mcp._visual_state._parser_client, MockOmniParserClient
    )  # Verify parser mock was used

    # --- Test case with change ---
    img1 = Image.new("RGB", (100, 100), color="blue")
    img2 = img1.copy()
    ImageDraw.Draw(img2).rectangle([(10, 10), (50, 50)], fill="red")  # Draw a change

    # Simulate 'before' state update
    mock_take_screenshot.return_value = img1
    mcp._visual_state.update()
    before_img = mcp._visual_state._last_screenshot
    assert mcp._visual_state.screen_dimensions == (100, 100)

    # Simulate 'after' state update
    mock_take_screenshot.return_value = img2
    mcp._visual_state.update()
    after_img = mcp._visual_state._last_screenshot

    # --- Call verification method on the OmniMCP instance ---
    verification_result = mcp._verify_action(before_img, after_img)

    assert isinstance(verification_result, ActionVerification)
    assert verification_result.success is True, (
        "Verification failed for image with changes"
    )
    assert verification_result.confidence > 0.0

    # --- Test case with no change ---
    mock_take_screenshot.return_value = img1  # Reset screenshot
    mcp._visual_state.update()  # Update state to img1
    after_img_no_change = mcp._visual_state._last_screenshot

    verification_no_change = mcp._verify_action(
        before_img, after_img_no_change
    )  # Compare img1 with img1

    assert isinstance(verification_no_change, ActionVerification)
    assert verification_no_change.success is False, (
        "Verification succeeded for images with no change"
    )
    assert verification_no_change.confidence == 0.0
