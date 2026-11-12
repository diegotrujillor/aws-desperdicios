"""AWS session and region resolution."""
import boto3
from botocore.exceptions import ProfileNotFound

from aws_desperdicios.errors import AwsSetupError

# Region used only to call ec2:DescribeRegions when the session has no default region.
DISCOVERY_REGION = "us-east-1"


def create_session(profile: str | None) -> boto3.Session:
    """Create a session from an AWS CLI profile, or from the default credential chain."""
    try:
        return boto3.Session(profile_name=profile)
    except ProfileNotFound as error:
        raise AwsSetupError(
            f"No existe el perfil '{profile}' en tu configuración de AWS CLI (~/.aws/config)."
        ) from error


def resolve_regions(session: boto3.Session, region: str | None) -> list[str]:
    """Return [region] if given; otherwise every region enabled for the account, sorted."""
    if region:
        return [region]
    ec2 = session.client("ec2", region_name=session.region_name or DISCOVERY_REGION)
    # Without AllRegions, DescribeRegions returns only regions enabled for the account.
    response = ec2.describe_regions()
    return sorted(r["RegionName"] for r in response["Regions"])
