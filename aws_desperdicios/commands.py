"""Build AWS CLI commands to suggest (never run) for a finding."""
import shlex


def aws_cli(service: str, operation: str, region: str, profile: str | None, *params: str) -> str:
    """Shell-safe AWS CLI command line, e.g. aws ec2 delete-volume --region X --volume-id Y."""
    parts = ["aws", service, operation]
    if profile:
        parts += ["--profile", profile]
    parts += ["--region", region, *params]
    return shlex.join(parts)
