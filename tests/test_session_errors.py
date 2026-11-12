import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

from aws_desperdicios.errors import AwsSetupError, explain_error, iam_action_name
from aws_desperdicios.session import create_session, resolve_regions


def client_error(code, message="", operation="DescribeVolumes"):
    return ClientError({"Error": {"Code": code, "Message": message}}, operation)


def test_unknown_profile_raises_spanish_setup_error():
    with pytest.raises(AwsSetupError, match="perfil 'no-existe'"):
        create_session("no-existe")


def test_session_without_profile_uses_default_chain():
    assert create_session(None).profile_name == "default"


def test_explicit_region_skips_region_discovery(session, api_calls):
    assert resolve_regions(session, "sa-east-1") == ["sa-east-1"]
    assert api_calls == set()


def test_discovers_enabled_regions_sorted(session, api_calls):
    regions = resolve_regions(session, None)

    assert "us-east-1" in regions and "sa-east-1" in regions
    assert regions == sorted(regions)
    assert api_calls == {"ec2:DescribeRegions"}


@pytest.mark.parametrize("code", ["AccessDenied", "AccessDeniedException", "UnauthorizedOperation"])
def test_access_denied_names_the_missing_permission(code):
    message = explain_error(client_error(code), last_action="ec2:DescribeVolumes")
    assert "Falta el permiso IAM 'ec2:DescribeVolumes'" in message
    assert "iam/politica-minima.json" in message


def test_permission_is_taken_from_aws_message_when_present():
    error = client_error(
        "AccessDeniedException",
        "User: arn:aws:iam::123:user/x is not authorized to perform: logs:DescribeLogGroups on resource",
    )
    assert "'logs:DescribeLogGroups'" in explain_error(error, last_action="ec2:DescribeVolumes")


def test_other_client_errors_show_code_and_message():
    message = explain_error(client_error("Throttling", "Rate exceeded"))
    assert "Throttling" in message and "Rate exceeded" in message


def test_missing_credentials_message_is_in_spanish():
    assert "No se encontraron credenciales" in explain_error(NoCredentialsError())


def test_network_error_message_is_in_spanish():
    error = EndpointConnectionError(endpoint_url="https://ec2.us-east-1.amazonaws.com")
    assert "No fue posible conectarse" in explain_error(error)


def test_unexpected_exceptions_are_not_swallowed():
    with pytest.raises(TypeError):
        explain_error(ValueError("boom"))


def test_iam_action_name_maps_cloudwatch_signing_name():
    model = boto3.client("cloudwatch", region_name="us-east-1").meta.service_model
    assert iam_action_name(model.operation_model("GetMetricStatistics")) == "cloudwatch:GetMetricStatistics"
