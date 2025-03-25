# omnimcp/omniparser/server.py

"""Deployment module for OmniParser on AWS EC2 with on-demand startup and auto-shutdown."""

import datetime
import os
import subprocess
import time
import json
import io
import zipfile

from botocore.exceptions import ClientError
from loguru import logger
import boto3
import fire
import paramiko

from omnimcp.config import config

# Update default configuration values
# config.AWS_EC2_INSTANCE_TYPE = "g4dn.xlarge"  # 4 vCPU, 16GB RAM, T4 GPU
# config.INACTIVITY_TIMEOUT_MINUTES = 20  # Auto-shutdown after 20min inactivity

# Lambda function name for auto-shutdown
LAMBDA_FUNCTION_NAME = f"{config.PROJECT_NAME}-auto-shutdown"
# CloudWatch rule name for monitoring
CLOUDWATCH_RULE_NAME = f"{config.PROJECT_NAME}-inactivity-monitor"
# API Gateway name for instance discovery
API_GATEWAY_NAME = f"{config.PROJECT_NAME}-discovery"

CLEANUP_ON_FAILURE = False


def create_key_pair(
    key_name: str = config.AWS_EC2_KEY_NAME, key_path: str = config.AWS_EC2_KEY_PATH
) -> str | None:
    """Create an EC2 key pair.

    Args:
        key_name: Name of the key pair
        key_path: Path where to save the key file

    Returns:
        str | None: Key name if successful, None otherwise
    """
    ec2_client = boto3.client("ec2", region_name=config.AWS_REGION)
    try:
        key_pair = ec2_client.create_key_pair(KeyName=key_name)
        private_key = key_pair["KeyMaterial"]

        with open(key_path, "w") as key_file:
            key_file.write(private_key)
        os.chmod(key_path, 0o400)  # Set read-only permissions

        logger.info(f"Key pair {key_name} created and saved to {key_path}")
        return key_name
    except ClientError as e:
        logger.error(f"Error creating key pair: {e}")
        return None


def get_or_create_security_group_id(ports: list[int] = [22, config.PORT]) -> str | None:
    """Get existing security group or create a new one.

    Args:
        ports: List of ports to open in the security group

    Returns:
        str | None: Security group ID if successful, None otherwise
    """
    ec2 = boto3.client("ec2", region_name=config.AWS_REGION)

    ip_permissions = [
        {
            "IpProtocol": "tcp",
            "FromPort": port,
            "ToPort": port,
            "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
        }
        for port in ports
    ]

    try:
        response = ec2.describe_security_groups(
            GroupNames=[config.AWS_EC2_SECURITY_GROUP]
        )
        security_group_id = response["SecurityGroups"][0]["GroupId"]
        logger.info(
            f"Security group '{config.AWS_EC2_SECURITY_GROUP}' already exists: "
            f"{security_group_id}"
        )

        for ip_permission in ip_permissions:
            try:
                ec2.authorize_security_group_ingress(
                    GroupId=security_group_id, IpPermissions=[ip_permission]
                )
                logger.info(f"Added inbound rule for port {ip_permission['FromPort']}")
            except ClientError as e:
                if e.response["Error"]["Code"] == "InvalidPermission.Duplicate":
                    logger.info(
                        f"Rule for port {ip_permission['FromPort']} already exists"
                    )
                else:
                    logger.error(
                        f"Error adding rule for port {ip_permission['FromPort']}: {e}"
                    )

        return security_group_id
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidGroup.NotFound":
            try:
                response = ec2.create_security_group(
                    GroupName=config.AWS_EC2_SECURITY_GROUP,
                    Description="Security group for OmniParser deployment",
                    TagSpecifications=[
                        {
                            "ResourceType": "security-group",
                            "Tags": [{"Key": "Name", "Value": config.PROJECT_NAME}],
                        }
                    ],
                )
                security_group_id = response["GroupId"]
                logger.info(
                    f"Created security group '{config.AWS_EC2_SECURITY_GROUP}' "
                    f"with ID: {security_group_id}"
                )

                ec2.authorize_security_group_ingress(
                    GroupId=security_group_id, IpPermissions=ip_permissions
                )
                logger.info(f"Added inbound rules for ports {ports}")

                return security_group_id
            except ClientError as e:
                logger.error(f"Error creating security group: {e}")
                return None
        else:
            logger.error(f"Error describing security groups: {e}")
            return None


def deploy_ec2_instance(
    ami: str = config.AWS_EC2_AMI,
    instance_type: str = config.AWS_EC2_INSTANCE_TYPE,
    project_name: str = config.PROJECT_NAME,
    key_name: str = config.AWS_EC2_KEY_NAME,
    disk_size: int = config.AWS_EC2_DISK_SIZE,
) -> tuple[str | None, str | None]:
    """Deploy a new EC2 instance or return existing one.

    Args:
        ami: AMI ID to use for the instance
        instance_type: EC2 instance type
        project_name: Name tag for the instance
        key_name: Name of the key pair to use
        disk_size: Size of the root volume in GB

    Returns:
        tuple[str | None, str | None]: Instance ID and public IP if successful
    """
    ec2 = boto3.resource("ec2", region_name=config.AWS_REGION)
    ec2_client = boto3.client("ec2", region_name=config.AWS_REGION)

    # Check for existing instances first
    instances = ec2.instances.filter(
        Filters=[
            {"Name": "tag:Name", "Values": [config.PROJECT_NAME]},
            {
                "Name": "instance-state-name",
                "Values": ["running", "pending", "stopped"],
            },
        ]
    )

    existing_instance = None
    for instance in instances:
        existing_instance = instance
        if instance.state["Name"] == "running":
            logger.info(
                f"Instance already running: ID - {instance.id}, "
                f"IP - {instance.public_ip_address}"
            )
            break
        elif instance.state["Name"] == "stopped":
            logger.info(f"Starting existing stopped instance: ID - {instance.id}")
            ec2_client.start_instances(InstanceIds=[instance.id])
            instance.wait_until_running()
            instance.reload()
            logger.info(
                f"Instance started: ID - {instance.id}, "
                f"IP - {instance.public_ip_address}"
            )
            break

    # If we found an existing instance, ensure we have its key
    if existing_instance:
        if not os.path.exists(config.AWS_EC2_KEY_PATH):
            logger.warning(
                f"Key file {config.AWS_EC2_KEY_PATH} not found for existing instance."
            )
            logger.warning(
                "You'll need to use the original key file to connect to this instance."
            )
            logger.warning(
                "Consider terminating the instance with 'deploy.py stop' and starting "
                "fresh."
            )
            return None, None
        return existing_instance.id, existing_instance.public_ip_address

    # No existing instance found, create new one with new key pair
    security_group_id = get_or_create_security_group_id()
    if not security_group_id:
        logger.error(
            "Unable to retrieve security group ID. Instance deployment aborted."
        )
        return None, None

    # Create new key pair
    try:
        if os.path.exists(config.AWS_EC2_KEY_PATH):
            logger.info(f"Removing existing key file {config.AWS_EC2_KEY_PATH}")
            os.remove(config.AWS_EC2_KEY_PATH)

        try:
            ec2_client.delete_key_pair(KeyName=key_name)
            logger.info(f"Deleted existing key pair {key_name}")
        except ClientError:
            pass  # Key pair doesn't exist, which is fine

        if not create_key_pair(key_name):
            logger.error("Failed to create key pair")
            return None, None
    except Exception as e:
        logger.error(f"Error managing key pair: {e}")
        return None, None

    # Create new instance with improved EBS configuration for gp3
    ebs_config = {
        "DeviceName": "/dev/sda1",
        "Ebs": {
            "VolumeSize": disk_size,
            "VolumeType": "gp3",  # Explicitly set to gp3
            "DeleteOnTermination": True,
            "Iops": 3000,  # Default for gp3
            "Throughput": 125,  # Default for gp3
        },
    }

    new_instance = ec2.create_instances(
        ImageId=ami,
        MinCount=1,
        MaxCount=1,
        InstanceType=instance_type,
        KeyName=key_name,
        SecurityGroupIds=[security_group_id],
        BlockDeviceMappings=[ebs_config],
        TagSpecifications=[
            {
                "ResourceType": "instance",
                "Tags": [{"Key": "Name", "Value": project_name}],
            },
        ],
    )[0]

    new_instance.wait_until_running()
    new_instance.reload()
    logger.info(
        f"New instance created: ID - {new_instance.id}, "
        f"IP - {new_instance.public_ip_address}"
    )
    return new_instance.id, new_instance.public_ip_address


def configure_ec2_instance(
    instance_id: str | None = None,
    instance_ip: str | None = None,
    max_ssh_retries: int = 20,
    ssh_retry_delay: int = 20,
    max_cmd_retries: int = 20,
    cmd_retry_delay: int = 30,
) -> tuple[str | None, str | None]:
    """Configure an EC2 instance with necessary dependencies and Docker setup.

    This function either configures an existing EC2 instance specified by instance_id
    and instance_ip, or deploys and configures a new instance. It installs Docker and
    other required dependencies, and sets up the environment for running containers.

    Args:
        instance_id: Optional ID of an existing EC2 instance to configure.
            If None, a new instance will be deployed.
        instance_ip: Optional IP address of an existing EC2 instance.
            Required if instance_id is provided.
        max_ssh_retries: Maximum number of SSH connection attempts.
            Defaults to 20 attempts.
        ssh_retry_delay: Delay in seconds between SSH connection attempts.
            Defaults to 20 seconds.
        max_cmd_retries: Maximum number of command execution retries.
            Defaults to 20 attempts.
        cmd_retry_delay: Delay in seconds between command execution retries.
            Defaults to 30 seconds.

    Returns:
        tuple[str | None, str | None]: A tuple containing:
            - The instance ID (str) or None if configuration failed
            - The instance's public IP address (str) or None if configuration failed

    Raises:
        RuntimeError: If command execution fails
        paramiko.SSHException: If SSH connection fails
        Exception: For other unexpected errors during configuration
    """
    if not instance_id:
        ec2_instance_id, ec2_instance_ip = deploy_ec2_instance()
    else:
        ec2_instance_id = instance_id
        ec2_instance_ip = instance_ip

    key = paramiko.RSAKey.from_private_key_file(config.AWS_EC2_KEY_PATH)
    ssh_client = paramiko.SSHClient()
    ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    ssh_retries = 0
    while ssh_retries < max_ssh_retries:
        try:
            ssh_client.connect(
                hostname=ec2_instance_ip, username=config.AWS_EC2_USER, pkey=key
            )
            break
        except Exception as e:
            ssh_retries += 1
            logger.error(f"SSH connection attempt {ssh_retries} failed: {e}")
            if ssh_retries < max_ssh_retries:
                logger.info(f"Retrying SSH connection in {ssh_retry_delay} seconds...")
                time.sleep(ssh_retry_delay)
            else:
                logger.error("Maximum SSH connection attempts reached. Aborting.")
                return None, None

    commands = [
        "sudo apt-get update",
        "sudo apt-get install -y ca-certificates curl gnupg",
        "sudo install -m 0755 -d /etc/apt/keyrings",
        (
            "curl -fsSL https://download.docker.com/linux/ubuntu/gpg | "
            "sudo dd of=/etc/apt/keyrings/docker.gpg"
        ),
        "sudo chmod a+r /etc/apt/keyrings/docker.gpg",
        (
            'echo "deb [arch="$(dpkg --print-architecture)" '
            "signed-by=/etc/apt/keyrings/docker.gpg] "
            "https://download.docker.com/linux/ubuntu "
            '"$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | '
            "sudo tee /etc/apt/sources.list.d/docker.list > /dev/null"
        ),
        "sudo apt-get update",
        (
            "sudo apt-get install -y docker-ce docker-ce-cli containerd.io "
            "docker-buildx-plugin docker-compose-plugin"
        ),
        "sudo systemctl start docker",
        "sudo systemctl enable docker",
        "sudo usermod -a -G docker ${USER}",
        "sudo docker system prune -af --volumes",
        f"sudo docker rm -f {config.PROJECT_NAME}-container || true",
    ]

    for command in commands:
        logger.info(f"Executing command: {command}")
        cmd_retries = 0
        while cmd_retries < max_cmd_retries:
            stdin, stdout, stderr = ssh_client.exec_command(command)
            exit_status = stdout.channel.recv_exit_status()

            if exit_status == 0:
                logger.info("Command executed successfully")
                break
            else:
                error_message = stderr.read()
                if "Could not get lock" in str(error_message):
                    cmd_retries += 1
                    logger.warning(
                        f"dpkg is locked, retrying in {cmd_retry_delay} seconds... "
                        f"Attempt {cmd_retries}/{max_cmd_retries}"
                    )
                    time.sleep(cmd_retry_delay)
                else:
                    logger.error(
                        f"Error in command: {command}, Exit Status: {exit_status}, "
                        f"Error: {error_message}"
                    )
                    break

    ssh_client.close()
    return ec2_instance_id, ec2_instance_ip


def execute_command(ssh_client: paramiko.SSHClient, command: str) -> None:
    """Execute a command and handle its output safely."""
    logger.info(f"Executing: {command}")
    stdin, stdout, stderr = ssh_client.exec_command(
        command,
        timeout=config.COMMAND_TIMEOUT,
        # get_pty=True
    )

    # Stream output in real-time
    while not stdout.channel.exit_status_ready():
        if stdout.channel.recv_ready():
            try:
                line = stdout.channel.recv(1024).decode("utf-8", errors="replace")
                if line.strip():  # Only log non-empty lines
                    logger.info(line.strip())
            except Exception as e:
                logger.warning(f"Error decoding stdout: {e}")

        if stdout.channel.recv_stderr_ready():
            try:
                line = stdout.channel.recv_stderr(1024).decode(
                    "utf-8", errors="replace"
                )
                if line.strip():  # Only log non-empty lines
                    logger.error(line.strip())
            except Exception as e:
                logger.warning(f"Error decoding stderr: {e}")

    exit_status = stdout.channel.recv_exit_status()

    # Capture any remaining output
    try:
        remaining_stdout = stdout.read().decode("utf-8", errors="replace")
        if remaining_stdout.strip():
            logger.info(remaining_stdout.strip())
    except Exception as e:
        logger.warning(f"Error decoding remaining stdout: {e}")

    try:
        remaining_stderr = stderr.read().decode("utf-8", errors="replace")
        if remaining_stderr.strip():
            logger.error(remaining_stderr.strip())
    except Exception as e:
        logger.warning(f"Error decoding remaining stderr: {e}")

    if exit_status != 0:
        error_msg = f"Command failed with exit status {exit_status}: {command}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

    logger.info(f"Successfully executed: {command}")


def create_auto_shutdown_infrastructure(instance_id: str) -> None:
    """Create CloudWatch rule and Lambda function for auto-shutdown.

    Args:
        instance_id: ID of the EC2 instance to monitor
    """
    lambda_client = boto3.client("lambda", region_name=config.AWS_REGION)
    events_client = boto3.client("events", region_name=config.AWS_REGION)
    iam_client = boto3.client("iam", region_name=config.AWS_REGION)

    # Create IAM role for Lambda function
    try:
        assume_role_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }

        response = iam_client.create_role(
            RoleName=f"{config.PROJECT_NAME}-lambda-role",
            AssumeRolePolicyDocument=json.dumps(assume_role_policy),
        )

        role_arn = response["Role"]["Arn"]

        # Attach EC2 and CloudWatch permissions
        iam_client.attach_role_policy(
            RoleName=f"{config.PROJECT_NAME}-lambda-role",
            PolicyArn="arn:aws:iam::aws:policy/AmazonEC2FullAccess",
        )

        iam_client.attach_role_policy(
            RoleName=f"{config.PROJECT_NAME}-lambda-role",
            PolicyArn="arn:aws:iam::aws:policy/CloudWatchLogsFullAccess",
        )

        logger.info(f"Created IAM role for Lambda function: {role_arn}")

        # Wait for role to be available
        time.sleep(10)

    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            logger.info("IAM role already exists, retrieving ARN...")
            response = iam_client.get_role(
                RoleName=f"{config.PROJECT_NAME}-lambda-role"
            )
            role_arn = response["Role"]["Arn"]
        else:
            logger.error(f"Error creating IAM role: {e}")
            return

    # Create Lambda function for auto-shutdown
    lambda_code = f"""
import boto3
import datetime
import json

def lambda_handler(event, context):
    ec2 = boto3.client('ec2', region_name='{config.AWS_REGION}')
    instance_id = '{instance_id}'

    # Check if the instance is running
    response = ec2.describe_instances(InstanceIds=[instance_id])
    state = response['Reservations'][0]['Instances'][0]['State']['Name']

    if state == 'running':
        print(f"Stopping instance {{instance_id}} due to inactivity")
        ec2.stop_instances(InstanceIds=[instance_id])
        return {{
            'statusCode': 200,
            'body': json.dumps('Instance stopped due to inactivity')
        }}
    else:
        print(f"Instance {{instance_id}} is not running (state: {{state}})")
        return {{
            'statusCode': 200,
            'body': json.dumps(f'Instance is in {{state}} state, no action taken')
        }}
    """

    try:
        # Delete existing function if it exists
        try:
            lambda_client.delete_function(FunctionName=LAMBDA_FUNCTION_NAME)
            logger.info(f"Deleted existing Lambda function: {LAMBDA_FUNCTION_NAME}")
        except ClientError:
            pass  # Function doesn't exist, which is fine

        # Create new function
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a") as zip_file:
            zip_file.writestr("lambda_function.py", lambda_code)

        response = lambda_client.create_function(
            FunctionName=LAMBDA_FUNCTION_NAME,
            Runtime="python3.9",
            Role=role_arn,
            Handler="lambda_function.lambda_handler",
            Code={"ZipFile": zip_buffer.getvalue()},
            Timeout=30,
            MemorySize=128,
            Description=f"Auto-shutdown function for {config.PROJECT_NAME} instance",
        )

        lambda_arn = response["FunctionArn"]
        logger.info(f"Created Lambda function: {lambda_arn}")

        # Create CloudWatch rule to trigger Lambda after inactivity
        try:
            events_client.delete_rule(Name=CLOUDWATCH_RULE_NAME)
            logger.info(f"Deleted existing CloudWatch rule: {CLOUDWATCH_RULE_NAME}")
        except ClientError:
            pass  # Rule doesn't exist, which is fine

        response = events_client.put_rule(
            Name=CLOUDWATCH_RULE_NAME,
            ScheduleExpression=f"rate({config.INACTIVITY_TIMEOUT_MINUTES} minutes)",
            State="ENABLED",
            Description=f"Monitors {config.PROJECT_NAME} instance for inactivity",
        )

        rule_arn = response["RuleArn"]
        logger.info(f"Created CloudWatch rule: {rule_arn}")

        # Add lambda permission to be invoked by CloudWatch
        try:
            lambda_client.add_permission(
                FunctionName=LAMBDA_FUNCTION_NAME,
                StatementId=f"{config.PROJECT_NAME}-cloudwatch-trigger",
                Action="lambda:InvokeFunction",
                Principal="events.amazonaws.com",
                SourceArn=rule_arn,
            )
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceConflictException":
                raise

        # Connect the rule to the Lambda function
        events_client.put_targets(
            Rule=CLOUDWATCH_RULE_NAME, Targets=[{"Id": "1", "Arn": lambda_arn}]
        )

        logger.info(
            f"Auto-shutdown infrastructure created successfully for {instance_id=}"
        )

    except Exception as e:
        logger.error(f"Error creating auto-shutdown infrastructure: {e}")


def create_instance_discovery_api() -> str:
    """Create API Gateway endpoint for instance discovery.

    Returns:
        str: The URL of the API Gateway endpoint
    """
    apigw_client = boto3.client("apigateway", region_name=config.AWS_REGION)
    lambda_client = boto3.client("lambda", region_name=config.AWS_REGION)
    iam_client = boto3.client("iam", region_name=config.AWS_REGION)

    # Create IAM role for Lambda function
    role_name = f"{config.PROJECT_NAME}-discovery-role"
    try:
        assume_role_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Effect": "Allow",
                    "Principal": {"Service": "lambda.amazonaws.com"},
                    "Action": "sts:AssumeRole",
                }
            ],
        }

        response = iam_client.create_role(
            RoleName=role_name, AssumeRolePolicyDocument=json.dumps(assume_role_policy)
        )

        role_arn = response["Role"]["Arn"]

        # Attach EC2 and CloudWatch permissions
        iam_client.attach_role_policy(
            RoleName=role_name, PolicyArn="arn:aws:iam::aws:policy/AmazonEC2FullAccess"
        )

        iam_client.attach_role_policy(
            RoleName=role_name,
            PolicyArn="arn:aws:iam::aws:policy/CloudWatchLogsFullAccess",
        )

        logger.info(f"Created IAM role for discovery Lambda function: {role_arn}")

        # Wait for role to be available
        time.sleep(10)

    except ClientError as e:
        if e.response["Error"]["Code"] == "EntityAlreadyExists":
            logger.info(f"IAM role {role_name} already exists, retrieving ARN...")
            response = iam_client.get_role(RoleName=role_name)
            role_arn = response["Role"]["Arn"]
        else:
            logger.error(f"Error creating IAM role: {e}")
            return "Error: Failed to create IAM role"

    # Create Lambda function for instance discovery
    lambda_function_name = f"{config.PROJECT_NAME}-discovery"
    lambda_code = f"""
import boto3
import json

def lambda_handler(event, context):
    ec2 = boto3.resource('ec2', region_name='{config.AWS_REGION}')
    ec2_client = boto3.client('ec2', region_name='{config.AWS_REGION}')

    # Find instance with project tag
    instances = list(ec2.instances.filter(
        Filters=[
            {{'Name': 'tag:Name', 'Values': ['{config.PROJECT_NAME}']}},
            {{'Name': 'instance-state-name', 'Values': ['pending', 'running', 'stopped']}}
        ]
    ))

    if not instances:
        return {{
            'statusCode': 404,
            'headers': {{'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}},
            'body': json.dumps({{'error': 'No instance found'}})
        }}

    instance = instances[0]

    # Start the instance if it's stopped
    if instance.state['Name'] == 'stopped':
        try:
            ec2_client.start_instances(InstanceIds=[instance.id])
            return {{
                'statusCode': 202,
                'headers': {{'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}},
                'body': json.dumps({{
                    'instance_id': instance.id,
                    'status': 'starting',
                    'message': 'Instance is starting. Please try again in a few minutes.'
                }})
            }}
        except Exception as e:
            return {{
                'statusCode': 500,
                'headers': {{'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}},
                'body': json.dumps({{'error': f'Failed to start instance: {{str(e)}}'}})
            }}

    # Return info for running instance
    if instance.state['Name'] == 'running':
        return {{
            'statusCode': 200,
            'headers': {{'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}},
            'body': json.dumps({{
                'instance_id': instance.id,
                'public_ip': instance.public_ip_address,
                'status': instance.state['Name'],
                'api_url': f'http://{{instance.public_ip_address}}:{config.PORT}'
            }})
        }}

    # Instance is in another state (e.g., pending)
    return {{
        'statusCode': 202,
        'headers': {{'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*'}},
        'body': json.dumps({{
            'instance_id': instance.id,
            'status': instance.state['Name'],
            'message': f'Instance is {{instance.state["Name"]}}. Please try again shortly.'
        }})
    }}
    """

    try:
        # Delete existing function if it exists
        try:
            lambda_client.delete_function(FunctionName=lambda_function_name)
            logger.info(f"Deleted existing Lambda function: {lambda_function_name}")
        except ClientError:
            pass  # Function doesn't exist, which is fine

        # Create new function
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "a") as zip_file:
            zip_file.writestr("lambda_function.py", lambda_code)

        response = lambda_client.create_function(
            FunctionName=lambda_function_name,
            Runtime="python3.9",
            Role=role_arn,
            Handler="lambda_function.lambda_handler",
            Code={"ZipFile": zip_buffer.getvalue()},
            Timeout=30,
            MemorySize=128,
            Description=f"Discovery function for {config.PROJECT_NAME} instance",
        )

        lambda_arn = response["FunctionArn"]
        logger.info(f"Created discovery Lambda function: {lambda_arn}")

        # Create REST API
        try:
            # Find existing API
            apis = apigw_client.get_rest_apis()
            api_id = None

            for api in apis["items"]:
                if api["name"] == API_GATEWAY_NAME:
                    api_id = api["id"]
                    logger.info(f"Found existing API Gateway: {api_id}")
                    break

            if not api_id:
                # Create new API
                response = apigw_client.create_rest_api(
                    name=API_GATEWAY_NAME,
                    description=f"API for discovering {config.PROJECT_NAME} instances",
                    endpointConfiguration={"types": ["REGIONAL"]},
                )
                api_id = response["id"]
                logger.info(f"Created new API Gateway: {api_id}")

            # Get resources
            resources = apigw_client.get_resources(restApiId=api_id)
            root_id = None
            resource_id = None

            for resource in resources["items"]:
                if resource["path"] == "/":
                    root_id = resource["id"]
                elif resource["path"] == "/discover":
                    resource_id = resource["id"]

            # Create resource if not exists
            if not resource_id:
                response = apigw_client.create_resource(
                    restApiId=api_id, parentId=root_id, pathPart="discover"
                )
                resource_id = response["id"]
                logger.info("Created API resource: /discover")

            # Create GET method
            try:
                apigw_client.put_method(
                    restApiId=api_id,
                    resourceId=resource_id,
                    httpMethod="GET",
                    authorizationType="NONE",
                    apiKeyRequired=False,
                )
                logger.info("Created API method: GET /discover")
            except ClientError as e:
                if e.response["Error"]["Code"] != "ConflictException":
                    raise
                logger.info("API method GET /discover already exists")

            # Set Lambda integration
            try:
                apigw_client.put_integration(
                    restApiId=api_id,
                    resourceId=resource_id,
                    httpMethod="GET",
                    type="AWS_PROXY",
                    integrationHttpMethod="POST",
                    uri=(
                        f"arn:aws:apigateway:{config.AWS_REGION}:lambda:path/2015-03-31"
                        f"/functions/{lambda_arn}/invocations"
                    ),
                )
                logger.info("Set Lambda integration for GET /discover")
            except ClientError as e:
                if e.response["Error"]["Code"] != "ConflictException":
                    raise
                # Update existing integration
                apigw_client.update_integration(
                    restApiId=api_id,
                    resourceId=resource_id,
                    httpMethod="GET",
                    patchOperations=[
                        {
                            "op": "replace",
                            "path": "/uri",
                            "value": (
                                f"arn:aws:apigateway:{config.AWS_REGION}:lambda:path/"
                                f"2015-03-31/functions/{lambda_arn}/invocations"
                            ),
                        }
                    ],
                )
                logger.info("Updated Lambda integration for GET /discover")

            # Set Lambda permissions
            try:
                source_arn = (
                    f"arn:aws:execute-api:{config.AWS_REGION}:*:{api_id}/*/GET/discover"
                )
                lambda_client.add_permission(
                    FunctionName=lambda_function_name,
                    StatementId=f"{config.PROJECT_NAME}-apigw-permission",
                    Action="lambda:InvokeFunction",
                    Principal="apigateway.amazonaws.com",
                    SourceArn=source_arn,
                )
                logger.info("Added Lambda permission for API Gateway")
            except ClientError as e:
                if e.response["Error"]["Code"] != "ResourceConflictException":
                    raise
                logger.info("Lambda permission for API Gateway already exists")

            # Deploy API
            deployment = apigw_client.create_deployment(
                restApiId=api_id, stageName="prod"
            )
            logger.info(f"Deployed API Gateway: {deployment=}")

            # Return API endpoint
            api_endpoint = (
                f"https://{api_id}.execute-api."
                f"{config.AWS_REGION}.amazonaws.com/prod/discover"
            )
            logger.info(f"API Gateway endpoint: {api_endpoint}")
            return api_endpoint

        except Exception as e:
            logger.error(f"Error creating or updating API Gateway: {e}")
            return "Error: Failed to create API Gateway"

    except Exception as e:
        logger.error(f"Error creating discovery infrastructure: {e}")
        return "Error: Failed to create discovery infrastructure"


class Deploy:
    """Class handling deployment operations for OmniParser."""

    @staticmethod
    def start() -> None:
        """Start a new deployment of OmniParser on EC2."""
        try:
            instance_id, instance_ip = configure_ec2_instance()
            if not instance_id or not instance_ip:
                logger.error("Failed to deploy or configure EC2 instance")
                return

            # Set up auto-shutdown infrastructure
            create_auto_shutdown_infrastructure(instance_id)

            # Trigger driver installation via login shell
            Deploy.ssh(non_interactive=True)

            # Get the directory containing deploy.py
            current_dir = os.path.dirname(os.path.abspath(__file__))

            # Define files to copy
            files_to_copy = {
                "Dockerfile": os.path.join(current_dir, "Dockerfile"),
                ".dockerignore": os.path.join(current_dir, ".dockerignore"),
            }

            # Copy files to instance
            for filename, filepath in files_to_copy.items():
                if os.path.exists(filepath):
                    logger.info(f"Copying {filename} to instance...")
                    subprocess.run(
                        [
                            "scp",
                            "-i",
                            config.AWS_EC2_KEY_PATH,
                            "-o",
                            "StrictHostKeyChecking=no",
                            filepath,
                            f"{config.AWS_EC2_USER}@{instance_ip}:~/{filename}",
                        ],
                        check=True,
                    )
                else:
                    logger.warning(f"File not found: {filepath}")

            # Connect to instance and execute commands
            key = paramiko.RSAKey.from_private_key_file(config.AWS_EC2_KEY_PATH)
            ssh_client = paramiko.SSHClient()
            ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            try:
                logger.info(f"Connecting to {instance_ip}...")
                ssh_client.connect(
                    hostname=instance_ip,
                    username=config.AWS_EC2_USER,
                    pkey=key,
                    timeout=30,
                )

                setup_commands = [
                    "rm -rf OmniParser",  # Clean up any existing repo
                    f"git clone {config.REPO_URL}",
                    "cp Dockerfile .dockerignore OmniParser/",
                ]

                # Execute setup commands
                for command in setup_commands:
                    logger.info(f"Executing setup command: {command}")
                    execute_command(ssh_client, command)

                # Build and run Docker container
                docker_commands = [
                    # Remove any existing container
                    f"sudo docker rm -f {config.CONTAINER_NAME} || true",
                    # Remove any existing image
                    f"sudo docker rmi {config.PROJECT_NAME} || true",
                    # Build new image
                    (
                        "cd OmniParser && sudo docker build --progress=plain "
                        f"-t {config.PROJECT_NAME} ."
                    ),
                    # Run new container
                    (
                        "sudo docker run -d -p 8000:8000 --gpus all --name "
                        f"{config.CONTAINER_NAME} {config.PROJECT_NAME}"
                    ),
                ]

                # Execute Docker commands
                for command in docker_commands:
                    logger.info(f"Executing Docker command: {command}")
                    execute_command(ssh_client, command)

                # Wait for container to start and check its logs
                logger.info("Waiting for container to start...")
                time.sleep(10)  # Give container time to start
                execute_command(ssh_client, f"docker logs {config.CONTAINER_NAME}")

                # Wait for server to become responsive
                logger.info("Waiting for server to become responsive...")
                max_retries = 30
                retry_delay = 10
                server_ready = False

                for attempt in range(max_retries):
                    try:
                        # Check if server is responding
                        check_command = f"curl -s http://localhost:{config.PORT}/probe/"
                        execute_command(ssh_client, check_command)
                        server_ready = True
                        break
                    except Exception as e:
                        logger.warning(
                            f"Server not ready (attempt {attempt + 1}/{max_retries}): "
                            f"{e}"
                        )
                        if attempt < max_retries - 1:
                            logger.info(
                                f"Waiting {retry_delay} seconds before next attempt..."
                            )
                            time.sleep(retry_delay)

                if not server_ready:
                    raise RuntimeError("Server failed to start properly")

                # Final status check
                execute_command(ssh_client, f"docker ps | grep {config.CONTAINER_NAME}")

                # Create discovery API
                discovery_url = create_instance_discovery_api()
                logger.info(f"Instance discovery API available at: {discovery_url}")

                server_url = f"http://{instance_ip}:{config.PORT}"
                logger.info(f"Deployment complete. Server running at: {server_url}")
                logger.info(
                    f"Auto-shutdown after {config.INACTIVITY_TIMEOUT_MINUTES} minutes "
                    "of inactivity"
                )

                # Verify server is accessible from outside
                try:
                    import requests

                    response = requests.get(f"{server_url}/probe/", timeout=10)
                    if response.status_code == 200:
                        logger.info("Server is accessible from outside!")
                    else:
                        logger.warning(
                            f"Server responded with status code: {response.status_code}"
                        )
                except Exception as e:
                    logger.warning(f"Could not verify external access: {e}")

            except Exception as e:
                logger.error(f"Error during deployment: {e}")
                # Get container logs for debugging
                try:
                    execute_command(ssh_client, f"docker logs {config.CONTAINER_NAME}")
                except Exception as exc:
                    logger.warning(f"{exc=}")
                    pass
                raise

            finally:
                ssh_client.close()

        except Exception as e:
            logger.error(f"Deployment failed: {e}")
            if CLEANUP_ON_FAILURE:
                # Attempt cleanup on failure
                try:
                    Deploy.stop()
                except Exception as cleanup_error:
                    logger.error(f"Cleanup after failure also failed: {cleanup_error}")
            raise

        logger.info("Deployment completed successfully!")

    @staticmethod
    def status() -> None:
        """Check the status of deployed instances."""
        ec2 = boto3.resource("ec2", region_name=config.AWS_REGION)
        instances = ec2.instances.filter(
            Filters=[{"Name": "tag:Name", "Values": [config.PROJECT_NAME]}]
        )

        for instance in instances:
            public_ip = instance.public_ip_address
            if public_ip:
                server_url = f"http://{public_ip}:{config.PORT}"
                logger.info(
                    f"Instance ID: {instance.id}, State: {instance.state['Name']}, "
                    f"URL: {server_url}"
                )
            else:
                logger.info(
                    f"Instance ID: {instance.id}, State: {instance.state['Name']}, "
                    f"URL: Not available (no public IP)"
                )

        # Check auto-shutdown infrastructure
        lambda_client = boto3.client("lambda", region_name=config.AWS_REGION)
        events_client = boto3.client("events", region_name=config.AWS_REGION)

        try:
            lambda_response = lambda_client.get_function(
                FunctionName=LAMBDA_FUNCTION_NAME
            )
            logger.info(f"Auto-shutdown Lambda: {LAMBDA_FUNCTION_NAME} (Active)")
            logger.debug(f"{lambda_response=}")
        except ClientError:
            logger.info("Auto-shutdown Lambda: Not configured")

        try:
            rule_response = events_client.describe_rule(Name=CLOUDWATCH_RULE_NAME)
            logger.info(
                f"CloudWatch rule: {CLOUDWATCH_RULE_NAME} "
                f"(State: {rule_response['State']})"
            )
            logger.info(
                f"Auto-shutdown interval: {config.INACTIVITY_TIMEOUT_MINUTES} minutes"
            )
        except ClientError:
            logger.info("CloudWatch rule: Not configured")

        # Check discovery API
        try:
            apigw_client = boto3.client("apigateway", region_name=config.AWS_REGION)
            apis = apigw_client.get_rest_apis()

            api_found = False
            for api in apis["items"]:
                if api["name"] == API_GATEWAY_NAME:
                    api_id = api["id"]
                    api_endpoint = (
                        f"https://{api_id}.execute-api"
                        f".{config.AWS_REGION}.amazonaws.com/prod/discover"
                    )
                    logger.info(f"Discovery API: {api_endpoint}")
                    api_found = True
                    break

            if not api_found:
                logger.info("Discovery API: Not configured")

        except ClientError as e:
            logger.error(f"Error checking API Gateway: {e}")

    @staticmethod
    def ssh(non_interactive: bool = False) -> None:
        # Get instance IP
        ec2 = boto3.resource("ec2", region_name=config.AWS_REGION)
        instances = ec2.instances.filter(
            Filters=[
                {"Name": "tag:Name", "Values": [config.PROJECT_NAME]},
                {"Name": "instance-state-name", "Values": ["running"]},
            ]
        )

        instance = next(iter(instances), None)
        if not instance:
            logger.error("No running instance found")
            return

        ip = instance.public_ip_address
        if not ip:
            logger.error("Instance has no public IP")
            return

        # Check if key file exists
        if not os.path.exists(config.AWS_EC2_KEY_PATH):
            logger.error(f"Key file not found: {config.AWS_EC2_KEY_PATH}")
            return

        if non_interactive:
            # Trigger driver installation (this might cause reboot)
            ssh_command = [
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-i",
                config.AWS_EC2_KEY_PATH,
                f"{config.AWS_EC2_USER}@{ip}",
                "-t",
                "-tt",
                "bash --login -c 'exit'",
            ]

            try:
                subprocess.run(ssh_command, check=True)
                logger.info("Initial SSH login completed successfully")
            except subprocess.CalledProcessError as e:
                logger.warning(f"Initial SSH connection closed: {e}")

            # Wait for potential reboot to complete
            logger.info(
                "Waiting for instance to be fully available after potential reboot..."
            )
            max_attempts = 20
            attempt = 0
            while attempt < max_attempts:
                attempt += 1
                logger.info(f"SSH connection attempt {attempt}/{max_attempts}")
                try:
                    # Check if we can make a new SSH connection
                    test_ssh_cmd = [
                        "ssh",
                        "-o",
                        "StrictHostKeyChecking=no",
                        "-o",
                        "ConnectTimeout=5",
                        "-o",
                        "UserKnownHostsFile=/dev/null",
                        "-i",
                        config.AWS_EC2_KEY_PATH,
                        f"{config.AWS_EC2_USER}@{ip}",
                        "echo 'SSH connection successful'",
                    ]
                    result = subprocess.run(
                        test_ssh_cmd, capture_output=True, text=True
                    )
                    if result.returncode == 0:
                        logger.info("Instance is ready for SSH connections")
                        return
                except Exception as e:
                    pass

                time.sleep(10)  # Wait 10 seconds between attempts

            logger.error("Failed to reconnect to instance after potential reboot")
        else:
            # Interactive SSH session
            ssh_command = f"ssh -i {config.AWS_EC2_KEY_PATH} -o StrictHostKeyChecking=no {config.AWS_EC2_USER}@{ip}"
            logger.info(f"Connecting with: {ssh_command}")
            os.system(ssh_command)
            return

    @staticmethod
    def stop(
        project_name: str = config.PROJECT_NAME,
        security_group_name: str = config.AWS_EC2_SECURITY_GROUP,
    ) -> None:
        """Terminates EC2 instance and deletes associated security group and resources.

        Args:
            project_name (str): The project name used to tag the instance.
                Defaults to config.PROJECT_NAME.
            security_group_name (str): The name of the security group to delete.
                Defaults to config.AWS_EC2_SECURITY_GROUP.
        """
        ec2_resource = boto3.resource("ec2", region_name=config.AWS_REGION)
        ec2_client = boto3.client("ec2", region_name=config.AWS_REGION)
        lambda_client = boto3.client("lambda", region_name=config.AWS_REGION)
        events_client = boto3.client("events", region_name=config.AWS_REGION)
        apigw_client = boto3.client("apigateway", region_name=config.AWS_REGION)
        iam_client = boto3.client("iam", region_name=config.AWS_REGION)

        # Terminate EC2 instances
        instances = ec2_resource.instances.filter(
            Filters=[
                {"Name": "tag:Name", "Values": [project_name]},
                {
                    "Name": "instance-state-name",
                    "Values": [
                        "pending",
                        "running",
                        "shutting-down",
                        "stopped",
                        "stopping",
                    ],
                },
            ]
        )

        for instance in instances:
            logger.info(f"Terminating instance: ID - {instance.id}")
            instance.terminate()
            instance.wait_until_terminated()
            logger.info(f"Instance {instance.id} terminated successfully.")

        # Delete CloudWatch rule and Lambda function
        try:
            events_client.remove_targets(Rule=CLOUDWATCH_RULE_NAME, Ids=["1"])
            events_client.delete_rule(Name=CLOUDWATCH_RULE_NAME)
            logger.info(f"Deleted CloudWatch rule: {CLOUDWATCH_RULE_NAME}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.info(f"CloudWatch rule {CLOUDWATCH_RULE_NAME} does not exist")
            else:
                logger.error(f"Error deleting CloudWatch rule: {e}")

        try:
            lambda_client.delete_function(FunctionName=LAMBDA_FUNCTION_NAME)
            logger.info(f"Deleted Lambda function: {LAMBDA_FUNCTION_NAME}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.info(f"Lambda function {LAMBDA_FUNCTION_NAME} does not exist")
            else:
                logger.error(f"Error deleting Lambda function: {e}")

        # Delete discovery Lambda and API Gateway
        try:
            # Find and delete API Gateway
            apis = apigw_client.get_rest_apis()
            for api in apis["items"]:
                if api["name"] == API_GATEWAY_NAME:
                    api_id = api["id"]
                    logger.info(f"Deleting API Gateway: {api_id}")
                    apigw_client.delete_rest_api(restApiId=api_id)
                    logger.info(f"Deleted API Gateway: {API_GATEWAY_NAME}")
                    break
        except ClientError as e:
            logger.error(f"Error deleting API Gateway: {e}")

        try:
            lambda_client.delete_function(
                FunctionName=f"{config.PROJECT_NAME}-discovery"
            )
            logger.info("Deleted discovery Lambda function")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                logger.error(f"Error deleting discovery Lambda function: {e}")

        # Delete IAM roles
        for role_name in [
            f"{config.PROJECT_NAME}-lambda-role",
            f"{config.PROJECT_NAME}-discovery-role",
        ]:
            try:
                # Detach policies first
                attached_policies = iam_client.list_attached_role_policies(
                    RoleName=role_name
                )
                for policy in attached_policies.get("AttachedPolicies", []):
                    iam_client.detach_role_policy(
                        RoleName=role_name, PolicyArn=policy["PolicyArn"]
                    )
                    logger.info(
                        f"Detached policy {policy['PolicyArn']} from role {role_name}"
                    )

                iam_client.delete_role(RoleName=role_name)
                logger.info(f"Deleted IAM role: {role_name}")
            except ClientError as e:
                if e.response["Error"]["Code"] != "NoSuchEntity":
                    logger.error(f"Error deleting IAM role {role_name}: {e}")

        # Delete security group
        try:
            ec2_client.delete_security_group(GroupName=security_group_name)
            logger.info(f"Deleted security group: {security_group_name}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvalidGroup.NotFound":
                logger.info(
                    f"Security group {security_group_name} does not exist or already "
                    "deleted."
                )
            else:
                logger.error(f"Error deleting security group: {e}")

        logger.info("Cleanup completed successfully.")

    @staticmethod
    def stop_instance(instance_id: str) -> None:
        """Stop a specific EC2 instance."""
        ec2_client = boto3.client("ec2", region_name=config.AWS_REGION)
        try:
            ec2_client.stop_instances(InstanceIds=[instance_id])
            logger.info(f"Stopped instance {instance_id}")
        except ClientError as e:
            logger.error(f"Error stopping instance {instance_id}: {e}")

    @staticmethod
    def start_instance(instance_id: str) -> str:
        """Start a specific EC2 instance and return its public IP."""
        ec2_client = boto3.client("ec2", region_name=config.AWS_REGION)
        ec2_resource = boto3.resource("ec2", region_name=config.AWS_REGION)

        try:
            ec2_client.start_instances(InstanceIds=[instance_id])
            logger.info(f"Starting instance {instance_id}...")

            instance = ec2_resource.Instance(instance_id)
            instance.wait_until_running()
            instance.reload()

            logger.info(
                f"Instance {instance_id} started, IP: {instance.public_ip_address}"
            )
            return instance.public_ip_address
        except ClientError as e:
            logger.error(f"Error starting instance {instance_id}: {e}")
            return None

    @staticmethod
    def history(days: int = 7) -> None:
        """Display deployment and auto-shutdown history.

        Args:
            days: Number of days of history to retrieve (default: 7)
        """
        logger.info(f"Retrieving {days} days of deployment history...")

        # Calculate time range
        end_time = datetime.datetime.now()
        start_time = end_time - datetime.timedelta(days=days)

        # Initialize AWS clients
        cloudwatch_logs = boto3.client("logs", region_name=config.AWS_REGION)
        ec2_client = boto3.client("ec2", region_name=config.AWS_REGION)

        # Get instance information
        instances = []
        try:
            response = ec2_client.describe_instances(
                Filters=[{"Name": "tag:Name", "Values": [config.PROJECT_NAME]}]
            )
            for reservation in response["Reservations"]:
                instances.extend(reservation["Instances"])

            logger.info(
                f"Found {len(instances)} instances with name tag '{config.PROJECT_NAME}'"
            )
        except Exception as e:
            logger.error(f"Error retrieving instances: {e}")

        # Display instance state transition history
        logger.info("\n=== Instance State History ===")
        for instance in instances:
            instance_id = instance["InstanceId"]
            try:
                # Get instance state transition history
                response = ec2_client.describe_instance_status(
                    InstanceIds=[instance_id], IncludeAllInstances=True
                )

                state = instance["State"]["Name"]
                launch_time = instance.get("LaunchTime", "Unknown")

                logger.info(
                    f"Instance {instance_id}: Current state={state}, Launch time={launch_time}"
                )

                # Get instance console output if available
                try:
                    console = ec2_client.get_console_output(InstanceId=instance_id)
                    if "Output" in console and console["Output"]:
                        logger.info("Last console output (truncated):")
                        # Show last few lines of console output
                        lines = console["Output"].strip().split("\n")
                        for line in lines[-10:]:
                            logger.info(f"  {line}")
                except Exception as e:
                    logger.info(f"Console output not available: {e}")

            except Exception as e:
                logger.error(f"Error retrieving status for instance {instance_id}: {e}")

        # Check for Lambda auto-shutdown logs
        logger.info("\n=== Auto-shutdown Lambda Logs ===")
        try:
            # Check if log group exists
            log_group_name = f"/aws/lambda/{LAMBDA_FUNCTION_NAME}"

            log_streams = cloudwatch_logs.describe_log_streams(
                logGroupName=log_group_name,
                orderBy="LastEventTime",
                descending=True,
                limit=5,
            )

            if not log_streams.get("logStreams"):
                logger.info("No log streams found for auto-shutdown Lambda")
            else:
                # Process the most recent log streams
                for stream in log_streams.get("logStreams", [])[:5]:
                    stream_name = stream["logStreamName"]
                    logger.info(f"Log stream: {stream_name}")

                    logs = cloudwatch_logs.get_log_events(
                        logGroupName=log_group_name,
                        logStreamName=stream_name,
                        startTime=int(start_time.timestamp() * 1000),
                        endTime=int(end_time.timestamp() * 1000),
                        limit=100,
                    )

                    if not logs.get("events"):
                        logger.info("  No events in this stream")
                        continue

                    for event in logs.get("events", []):
                        timestamp = datetime.datetime.fromtimestamp(
                            event["timestamp"] / 1000
                        )
                        message = event["message"]
                        logger.info(f"  {timestamp}: {message}")

        except cloudwatch_logs.exceptions.ResourceNotFoundException:
            logger.info(
                "No logs found for auto-shutdown Lambda. It may not have been triggered yet."
            )
        except Exception as e:
            logger.error(f"Error retrieving Lambda logs: {e}")

        # Check for discovery API logs if they exist
        logger.info("\n=== API Gateway Access Logs ===")
        try:
            # Find API ID first
            apigw_client = boto3.client("apigateway", region_name=config.AWS_REGION)
            apis = apigw_client.get_rest_apis()

            api_id = None
            for api in apis.get("items", []):
                if api["name"] == API_GATEWAY_NAME:
                    api_id = api["id"]
                    break

            if api_id:
                # API Gateway logs would be in a format like:
                # /aws/apigateway/{api-id}/stage-name
                log_group_name = f"API-Gateway-Execution-Logs_{api_id}/prod"

                try:
                    log_streams = cloudwatch_logs.describe_log_streams(
                        logGroupName=log_group_name,
                        orderBy="LastEventTime",
                        descending=True,
                        limit=5,
                    )

                    if not log_streams.get("logStreams"):
                        logger.info("No API Gateway access logs found")
                    else:
                        # Process log streams
                        for stream in log_streams.get("logStreams", [])[:3]:
                            stream_name = stream["logStreamName"]
                            logger.info(f"API access log stream: {stream_name}")

                            logs = cloudwatch_logs.get_log_events(
                                logGroupName=log_group_name,
                                logStreamName=stream_name,
                                startTime=int(start_time.timestamp() * 1000),
                                endTime=int(end_time.timestamp() * 1000),
                                limit=20,
                            )

                            for event in logs.get("events", []):
                                timestamp = datetime.datetime.fromtimestamp(
                                    event["timestamp"] / 1000
                                )
                                # API Gateway logs are often quite verbose, so truncate them
                                message = event["message"][:100] + (
                                    "..." if len(event["message"]) > 100 else ""
                                )
                                logger.info(f"  {timestamp}: {message}")

                except cloudwatch_logs.exceptions.ResourceNotFoundException:
                    logger.info("API Gateway logging is not enabled or no logs exist")
            else:
                logger.info(f"No API Gateway named {API_GATEWAY_NAME} found")

        except Exception as e:
            logger.error(f"Error retrieving API Gateway logs: {e}")

        logger.info("\nHistory retrieval complete.")


if __name__ == "__main__":
    fire.Fire(Deploy)
