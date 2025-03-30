"""End-to-end tests for OmniParser deployment and function."""

import os
import time
import pytest
from pathlib import Path
from PIL import Image

from loguru import logger
from omnimcp.omniparser.client import OmniParserClient, OmniParserProvider
from omnimcp.config import config


@pytest.fixture(scope="module")
def test_environment():
    """Fixture to set up test environment once for all tests."""
    # Initialize test environment
    test_image_path = Path(__file__).parent.parent / "test_images" / "synthetic_ui.png"
    provider = OmniParserProvider()

    # Skip tests if server not accessible and credentials not available
    try:
        if not provider.is_available() and not os.environ.get("AWS_ACCESS_KEY_ID"):
            logger.warning("No OmniParser server available and AWS credentials not set")
            logger.warning(
                "Either start a local server, set OMNIPARSER_URL, or add AWS credentials"
            )
            pytest.skip("No OmniParser server available and no way to deploy one")
    except ValueError as e:
        # Provider couldn't find a server and has no way to deploy one
        if not os.environ.get("AWS_ACCESS_KEY_ID"):
            logger.warning(f"Provider error: {e}")
            logger.warning("AWS credentials not set for deployment")
            pytest.skip(
                "No OmniParser server available and no credentials to deploy one"
            )

    # Verify test image exists
    assert test_image_path.exists(), f"Test image not found: {test_image_path}"
    test_image = Image.open(test_image_path)

    # Return test environment data
    return {
        "test_image_path": test_image_path,
        "test_image": test_image,
        "provider": provider,
    }


@pytest.mark.e2e
def test_server_availability(test_environment):
    """Test if OmniParser server is available or can be deployed."""
    provider = test_environment["provider"]

    # Create client with default URL
    client = OmniParserClient(provider.server_url)

    # Check if server is already available
    if client.check_server_available():
        logger.info("OmniParser server is already running")
        assert True
        return

    # Try to deploy server
    logger.info("OmniParser server not available, attempting deployment...")
    result = provider.deploy()

    # Allow more time for deployment
    max_retries = 3
    for retry in range(max_retries):
        if result:
            break
        logger.info(f"Deployment attempt {retry + 1}/{max_retries} failed, retrying...")
        time.sleep(10)  # Wait before retry
        result = provider.deploy()

    assert result, "OmniParser server deployment failed"

    # Verify server is responsive after deployment
    client = OmniParserClient(provider.server_url)
    assert (
        client.check_server_available()
    ), "OmniParser server not responsive after deployment"


@pytest.mark.e2e
def test_image_parsing(test_environment):
    """Test image parsing using the deployed server."""
    provider = test_environment["provider"]
    test_image = test_environment["test_image"]

    # Use provider server URL
    client = OmniParserClient(provider.server_url)

    # Verify server is available
    assert (
        client.check_server_available()
    ), "OmniParser server not available for parsing test"

    # Parse image
    result = client.parse_image(test_image)

    # Check basic response structure
    assert "parsed_content_list" in result, "Parsing result missing parsed_content_list"

    # Check for elements in the synthetic UI
    elements = result.get("parsed_content_list", [])
    logger.info(f"Found {len(elements)} UI elements in test image")

    # Synthetic image should have at least 3 elements
    assert len(elements) >= 3, "Too few elements found in synthetic UI image"

    # Log the first few elements found
    for i, element in enumerate(elements[:5]):
        element_type = element.get("type", "Unknown")
        content = element.get("content", "")
        bounds = element.get("bounds", {})
        logger.info(f"Element {i + 1}: {element_type} - '{content}' at {bounds}")

        # Each element should have basic properties
        assert "type" in element, f"Element {i + 1} missing 'type'"
        assert "bounds" in element, f"Element {i + 1} missing 'bounds'"

        if "bounds" in element:
            bounds = element["bounds"]
            assert "x" in bounds, f"Element {i + 1} bounds missing 'x'"
            assert "y" in bounds, f"Element {i + 1} bounds missing 'y'"
            assert "width" in bounds, f"Element {i + 1} bounds missing 'width'"
            assert "height" in bounds, f"Element {i + 1} bounds missing 'height'"
