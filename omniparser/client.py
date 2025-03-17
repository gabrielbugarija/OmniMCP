"""Client for interacting with the OmniParser server."""
from typing import Dict, Any, Optional
import io

from loguru import logger
import requests
from PIL import Image

from omnimcp.utils import image_to_base64
from omnimcp.omniparser.server.deploy import Deploy

class OmniParserClient:
    """Client for the OmniParser API."""

    def __init__(self, server_url: str = "http://localhost:8000"):
        """Initialize the OmniParser client.
        
        Args:
            server_url: URL of the OmniParser server. Defaults to localhost.
        """
        self.server_url = server_url.rstrip("/")

    def check_server_available(self) -> bool:
        """Check if the OmniParser server is available."""
        try:
            response = requests.get(f"{self.server_url}/probe/", timeout=5)
            response.raise_for_status()
            logger.info("OmniParser server is available")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"OmniParser server not available: {e}")
            return False

    def parse_image(self, image: Image.Image) -> Dict[str, Any]:
        """Parse an image using the OmniParser service.
        
        Args:
            image: PIL Image to parse
            
        Returns:
            Dict containing parsed UI elements and metadata
        """
        if not self.check_server_available():
            return {"error": "Server not available", "parsed_content_list": []}

        try:
            # Convert image to base64
            base64_image = image_to_base64(image)

            # Make request to API
            response = requests.post(
                f"{self.server_url}/parse/",
                json={"base64_image": base64_image},
                timeout=30
            )
            response.raise_for_status()

            # Parse response
            result = response.json()
            logger.info(f"OmniParser latency: {result.get('latency', 0):.2f}s")
            return result

        except Exception as e:
            logger.error(f"Error parsing image with OmniParser: {e}")
            return {"error": str(e), "parsed_content_list": []}

    def parse_screenshot(self, image_data: bytes) -> Dict[str, Any]:
        """Parse a screenshot using OmniParser.
        
        Args:
            image_data: Raw image data in bytes
            
        Returns:
            Dict containing parsed UI elements
        """
        try:
            image = Image.open(io.BytesIO(image_data))
            return self.parse_image(image)
        except Exception as e:
            logger.error(f"Error processing image data: {e}")
            return {"error": str(e), "parsed_content_list": []}


class OmniParserProvider:
    """Provider for OmniParser services with deployment capabilities."""

    def __init__(self, server_url: Optional[str] = None):
        self.server_url = server_url or "http://localhost:8000"
        self.client = OmniParserClient(self.server_url)

    def is_available(self) -> bool:
        return self.client.check_server_available()

    def deploy(self) -> bool:
        """Deploy OmniParser if not already running."""
        if self.is_available():
            logger.info("OmniParser service already running")
            return True

        try:
            logger.info("Deploying OmniParser service...")
            remote_url = Deploy.start()

            if remote_url and remote_url.startswith("http://"):
                logger.info(f"OmniParser deployed at: {remote_url}")
                self.server_url = remote_url
                self.client = OmniParserClient(self.server_url)
                return self.is_available()

        except Exception as e:
            logger.error(f"Failed to deploy OmniParser: {e}")
            return False

        return False
