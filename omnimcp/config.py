# omnimcp/config.py

"""Configuration management for OmniMCP."""

import os
from typing import Optional
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class OmniMCPConfig(BaseSettings):
    """Configuration settings for OmniMCP."""

    # Claude API configuration
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_DEFAULT_MODEL: str = "claude-3-7-sonnet-20250219"
    # ANTHROPIC_DEFAULT_MODEL: str = "claude-3-haiku-20240307"

    # Auto-shutdown OmniParser after 60min inactivity
    INACTIVITY_TIMEOUT_MINUTES: int = 60

    # OmniParser configuration
    OMNIPARSER_URL: Optional[str] = None

    # AWS deployment settings (for remote OmniParser)
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: Optional[str] = "us-west-2"

    # OmniParser deployment configuration
    PROJECT_NAME: str = "omniparser"
    REPO_URL: str = "https://github.com/microsoft/OmniParser.git"
    # AWS_EC2_AMI: str = "ami-06835d15c4de57810"
    AWS_EC2_AMI: str = (
        "ami-04631c7d8811d9bae"  # Official AWS DLAMI Base Ubuntu 22.04 (G6 Compatible)
    )
    AWS_EC2_DISK_SIZE: int = 128  # GB
    # AWS_EC2_INSTANCE_TYPE: str = "g4dn.xlarge"  # (T4 16GB $0.526/hr x86_64)
    AWS_EC2_INSTANCE_TYPE: str = "g6.xlarge"  # (L4 24GB $0.805/hr x86_64)
    # AWS_EC2_INSTANCE_TYPE: str = "p3.2xlarge"  # (V100 16GB $3.06/hr x86_64)
    AWS_EC2_USER: str = "ubuntu"
    PORT: int = 8000  # FastAPI port
    COMMAND_TIMEOUT: int = 600  # 10 minutes

    # Logging configuration
    LOG_DIR: Optional[str] = "logs"
    DISABLE_DEFAULT_LOGGING: bool = False

    # Run output configuration
    RUN_OUTPUT_DIR: str = "runs"

    # Debug settings
    # DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Properties for OmniParser deployment
    @property
    def CONTAINER_NAME(self) -> str:
        """Get the container name."""
        return f"{self.PROJECT_NAME}-container"

    @property
    def AWS_EC2_KEY_NAME(self) -> str:
        """Get the EC2 key pair name."""
        return f"{self.PROJECT_NAME}-key"

    @property
    def AWS_EC2_KEY_PATH(self) -> str:
        """Get the path to the EC2 key file."""
        # Store key files in the root directory
        root_dir = str(Path(__file__).parent.parent)
        return os.path.join(root_dir, f"{self.AWS_EC2_KEY_NAME}.pem")

    @property
    def AWS_EC2_SECURITY_GROUP(self) -> str:
        """Get the EC2 security group name."""
        return f"{self.PROJECT_NAME}-SecurityGroup"


# Create a global config instance
config = OmniMCPConfig()
