"""Tests for OmniParser deployment functionality."""

import pytest
import time
import boto3
import requests
from typing import List

from omnimcp.omniparser.server import Deploy
from omnimcp.omniparser.client import parse_image
from omnimcp.config import config
from omnimcp.tests.test_synthetic_ui import generate_test_ui


def get_running_parser_instances() -> List[dict]:
    """Get any running OmniParser instances."""
    ec2 = boto3.resource("ec2", region_name=config.AWS_REGION)
    instances = list(
        ec2.instances.filter(
            Filters=[
                {"Name": "tag:Name", "Values": [config.PROJECT_NAME]},
                {"Name": "instance-state-name", "Values": ["running"]},
            ]
        )
    )

    running_instances = []
    for instance in instances:
        if instance.public_ip_address:
            # Check if instance is responsive
            url = f"http://{instance.public_ip_address}:{config.PORT}/probe/"
            try:
                response = requests.get(url, timeout=5)
                if response.status_code == 200:
                    running_instances.append(
                        {
                            "id": instance.id,
                            "ip": instance.public_ip_address,
                            "url": f"http://{instance.public_ip_address}:{config.PORT}",
                        }
                    )
            except requests.exceptions.RequestException:
                pass

    return running_instances


def cleanup_parser_instances():
    """Stop all running parser instances."""
    Deploy.stop()


@pytest.fixture(scope="module")
def test_image():
    """Generate synthetic test image."""
    img, _ = generate_test_ui()
    return img


class TestParserDeployment:
    """Test suite for OmniParser deployment scenarios."""

    @classmethod
    def setup_class(cls):
        """Initial setup for all tests."""
        # Record initial state
        cls.initial_instances = get_running_parser_instances()
        print(f"\nInitial running instances: {len(cls.initial_instances)}")

    @classmethod
    def teardown_class(cls):
        """Cleanup after all tests."""
        cleanup_parser_instances()

        # Verify cleanup
        final_instances = get_running_parser_instances()
        assert len(final_instances) <= len(cls.initial_instances), (
            "Not all test instances were cleaned up"
        )

    @pytest.mark.skipif(
        condition=lambda: len(get_running_parser_instances()) > 0,
        reason="Skip if parser is already deployed",
    )
    def test_auto_deployment(self, test_image):
        """Test client auto-deploys when no instance exists."""
        # Ensure no instances are running
        running_instances = get_running_parser_instances()
        assert len(running_instances) == 0, "Test requires no running instances"

        # Use client - should trigger auto-deployment
        deployment_start = time.time()
        result = parse_image(test_image, None)  # None URL triggers auto-deployment
        deployment_time = time.time() - deployment_start

        # Verify deployment
        running_instances = get_running_parser_instances()
        assert len(running_instances) == 1, (
            f"Expected 1 running instance, found {len(running_instances)}"
        )

        # Verify result
        assert result is not None, "Parse result should not be None"
        assert "parsed_content_list" in result, "Result missing parsed content"

        print(f"\nAuto-deployment took {deployment_time:.1f} seconds")

    def test_use_existing_deployment(self, test_image):
        """Test client uses existing deployment if available."""
        # Get current running instances
        running_instances = get_running_parser_instances()
        if not running_instances:
            # Deploy if needed
            Deploy.start()
            time.sleep(10)  # Give time for deployment
            running_instances = get_running_parser_instances()

        assert len(running_instances) > 0, "Test requires at least one running instance"

        initial_instance = running_instances[0]
        print(f"\nUsing existing instance: {initial_instance['url']}")

        # Use client with existing deployment
        start_time = time.time()
        result = parse_image(test_image, initial_instance["url"])
        operation_time = time.time() - start_time

        # Verify no new instances were created
        current_instances = get_running_parser_instances()
        assert len(current_instances) == len(running_instances), (
            "Number of running instances changed"
        )

        # Verify result
        assert result is not None, "Parse result should not be None"
        assert "parsed_content_list" in result, "Result missing parsed content"

        print(f"Operation with existing deployment took {operation_time:.1f} seconds")

    def test_deployment_idempotency(self, test_image):
        """Test that multiple deployment attempts don't create duplicate instances."""
        # Get initial count
        initial_instances = get_running_parser_instances()
        initial_count = len(initial_instances)

        # Attempt multiple deployments
        for i in range(3):
            print(f"\nDeployment attempt {i + 1}")
            Deploy.start()
            time.sleep(5)

            current_instances = get_running_parser_instances()
            assert len(current_instances) <= initial_count + 1, (
                f"Unexpected number of instances: {len(current_instances)}"
            )

            # Verify client works with current deployment
            result = parse_image(test_image, current_instances[0]["url"])
            assert result is not None, "Parse operation failed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
