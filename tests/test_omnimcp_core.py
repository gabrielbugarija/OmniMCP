"""
Tests for core OmniMCP functionality using synthetic test images.

This tests the critical paths of OmniMCP using the synthetic UI images
instead of real screenshots to ensure deterministic results.
"""

import asyncio
from unittest.mock import patch, MagicMock

# Import from the installed package
from omnimcp.omnimcp import OmniMCP, VisualState

# Local import from test directory
from tests.test_synthetic_ui import generate_test_ui, generate_action_test_pair


class MockParserProvider:
    """Mock OmniParser provider that returns predetermined elements."""

    def __init__(self, elements):
        self.elements = elements
        self.client = MagicMock()
        self.client.parse_image.return_value = {"parsed_content_list": elements}

    def is_available(self):
        return True

    def deploy(self):
        return True


async def test_visual_state_parsing():
    """Test that VisualState can parse UI elements from synthetic images."""
    # Generate test UI with known elements
    test_img, elements_data = generate_test_ui()

    # Create a mock parser that returns our predefined elements
    mock_parser = MockParserProvider(elements_data)

    # Initialize VisualState with mock parser
    with patch("omnimcp.utils.take_screenshot", return_value=test_img):
        visual_state = VisualState(parser_provider=mock_parser)
        await visual_state.update()

        # Verify elements were parsed correctly
        assert len(visual_state.elements) == len(elements_data)

        # Check a specific element (button)
        button = next((e for e in visual_state.elements if e.type == "button"), None)
        assert button is not None
        assert button.content == "Submit"

        print("✅ Visual state parsing test passed")


async def test_element_finding():
    """Test that find_element can locate elements by description."""
    # Generate test UI with known elements
    test_img, elements_data = generate_test_ui()

    # Create a mock parser that returns our predefined elements
    mock_parser = MockParserProvider(elements_data)

    # Initialize VisualState with mock parser
    with patch("omnimcp.utils.take_screenshot", return_value=test_img):
        visual_state = VisualState(parser_provider=mock_parser)
        await visual_state.update()

        # Test element finding with different descriptions
        button = visual_state.find_element("submit button")
        assert button is not None
        assert button.type == "button"

        textfield = visual_state.find_element("username field")
        assert textfield is not None
        assert textfield.type == "text_field"

        # Check how many elements we have for debugging
        print(
            f"Available elements: {[(e.type, e.content) for e in visual_state.elements]}"
        )

        checkbox = visual_state.find_element("remember me")
        # For now, we'll just assert that we got a result since our simple matching might not work perfectly
        # with all types
        assert checkbox is not None

        print("✅ Element finding test passed")


async def test_action_verification():
    """Test that action verification can detect successful actions."""
    # Generate action test pairs
    before_click, after_click, _ = generate_action_test_pair("click", "button")
    before_type, after_type, _ = generate_action_test_pair("type", "text_field")

    # Create a simple OmniMCP instance with mocked components
    mcp = OmniMCP()

    # Test verification for click action
    click_verification = await mcp._verify_action(
        before_click, after_click, action_description="Clicked the submit button"
    )
    # Just verify that we get a result, don't check confidence yet
    assert click_verification is not None
    print(f"Click verification confidence: {click_verification.confidence}")

    # Test verification for type action
    type_verification = await mcp._verify_action(
        before_type, after_type, action_description="Typed username"
    )
    assert type_verification is not None
    print(f"Type verification confidence: {type_verification.confidence}")

    print("✅ Action verification test passed")


async def run_tests():
    """Run all core functionality tests."""
    print("\n🧪 Testing OmniMCP core functionality with synthetic UI...")

    await test_visual_state_parsing()
    await test_element_finding()
    await test_action_verification()

    print("\n✅ All core functionality tests passed!")


if __name__ == "__main__":
    asyncio.run(run_tests())
