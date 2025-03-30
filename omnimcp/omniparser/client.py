# omnimcp/omniparser/client.py

"""Client module for interacting with the OmniParser server."""

import base64
import time
from typing import Optional, Dict, List

import requests
from loguru import logger
from PIL import Image, ImageDraw

from .server import Deploy


class OmniParserClient:
    """Client for interacting with the OmniParser server."""

    def __init__(self, server_url: Optional[str] = None, auto_deploy: bool = True):
        """Initialize the OmniParser client.

        Args:
            server_url: URL of the OmniParser server. If None, will attempt to find
                or deploy a server.
            auto_deploy: Whether to automatically deploy a server if none is found.
        """
        self.server_url = server_url
        self.auto_deploy = auto_deploy
        self._ensure_server()

    def _ensure_server(self) -> None:
        """Ensure a server is available, deploying one if necessary."""
        if not self.server_url:
            # Try to find an existing server
            deployer = Deploy()
            deployer.status()  # This will log any running instances

            # Check if any instances are running
            import boto3

            ec2 = boto3.resource("ec2")
            instances = ec2.instances.filter(
                Filters=[
                    {"Name": "tag:Name", "Values": ["omniparser"]},
                    {"Name": "instance-state-name", "Values": ["running"]},
                ]
            )

            instance = next(iter(instances), None)
            if instance and instance.public_ip_address:
                self.server_url = f"http://{instance.public_ip_address}:8000"
                logger.info(f"Found existing server at {self.server_url}")
            elif self.auto_deploy:
                logger.info("No server found, deploying new instance...")
                deployer.start()
                # Wait for deployment and get URL
                max_retries = 30
                retry_delay = 10
                for i in range(max_retries):
                    instances = ec2.instances.filter(
                        Filters=[
                            {"Name": "tag:Name", "Values": ["omniparser"]},
                            {"Name": "instance-state-name", "Values": ["running"]},
                        ]
                    )
                    instance = next(iter(instances), None)
                    if instance and instance.public_ip_address:
                        self.server_url = f"http://{instance.public_ip_address}:8000"
                        break
                    time.sleep(retry_delay)
                else:
                    raise RuntimeError("Failed to deploy server")
            else:
                raise RuntimeError("No server URL provided and auto_deploy is disabled")

        # Verify server is responsive
        self._check_server()

    def _check_server(self) -> None:
        """Check if the server is responsive."""
        try:
            response = requests.get(f"{self.server_url}/probe/", timeout=10)
            response.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"Server not responsive: {e}")

    def parse_image(self, image: Image.Image) -> Dict:
        """Parse an image using the OmniParser server.

        Args:
            image: PIL Image to parse

        Returns:
            Dict containing parsing results
        """
        # Convert image to base64
        image_bytes = self._image_to_base64(image)

        # Make request
        try:
            response = requests.post(
                f"{self.server_url}/parse/",
                json={"base64_image": image_bytes},
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": f"Failed to parse image: {e}"}

    @staticmethod
    def _image_to_base64(image: Image.Image) -> str:
        """Convert PIL Image to base64 string."""
        import io

        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode()

    def visualize_results(
        self, image: Image.Image, parsed_content: List[Dict]
    ) -> Image.Image:
        """Visualize parsing results on the image.

        Args:
            image: Original PIL Image
            parsed_content: List of parsed content with bounding boxes

        Returns:
            PIL Image with visualizations
        """
        # Create copy of image
        viz_image = image.copy()
        draw = ImageDraw.Draw(viz_image)

        # Draw results
        for item in parsed_content:
            # Get coordinates
            x1, y1, x2, y2 = item["bbox"]
            x1 = int(x1 * image.width)
            y1 = int(y1 * image.height)
            x2 = int(x2 * image.width)
            y2 = int(y2 * image.height)

            # Draw box
            draw.rectangle([(x1, y1), (x2, y2)], outline="red", width=2)

            # Draw label
            label = item["content"]
            bbox = draw.textbbox((x1, y1), label)
            draw.rectangle(bbox, fill="white")
            draw.text((x1, y1), label, fill="red")

        return viz_image


# Example usage:
if __name__ == "__main__":
    # Create client (will auto-deploy if needed)
    client = OmniParserClient()

    # Parse an image
    image = Image.open("../OpenAdapt/tests/assets/excel.png")
    results = client.parse_image(image)

    # Visualize results
    if "error" not in results:
        viz_image = client.visualize_results(image, results["parsed_content_list"])
        viz_image.show()
