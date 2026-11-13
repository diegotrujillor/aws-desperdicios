"""Translate AWS errors into actionable Spanish messages for the user."""
import re

from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

ACCESS_DENIED_CODES = frozenset(
    {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "UnauthorizedAccess"}
)
# IAM uses "cloudwatch" while the API signing name is "monitoring".
IAM_PREFIX_OVERRIDES = {"monitoring": "cloudwatch"}
_ACTION_IN_MESSAGE = re.compile(r"perform: ([a-z0-9-]+:[A-Za-z0-9]+)")
POLICY_HINT = "Agrégalo a la política de solo lectura (ver iam/politica-minima.json)."


class AwsSetupError(Exception):
    """Fatal configuration problem (profile, credentials, price table). Message is user-facing."""


def iam_action_name(operation_model) -> str:
    """Return the IAM action (e.g. 'ec2:DescribeVolumes') for a botocore operation model."""
    metadata = operation_model.service_model.metadata
    prefix = metadata.get("signingName") or metadata["endpointPrefix"]
    return f"{IAM_PREFIX_OVERRIDES.get(prefix, prefix)}:{operation_model.name}"


def is_access_denied(error: ClientError) -> bool:
    return error.response.get("Error", {}).get("Code") in ACCESS_DENIED_CODES


def explain_error(error: Exception, last_action: str | None = None) -> str:
    """Spanish explanation for known AWS/botocore errors. Unknown exceptions raise TypeError."""
    if isinstance(error, NoCredentialsError):
        return (
            "No se encontraron credenciales de AWS. Configura un perfil con 'aws configure' "
            "y pásalo con --profile, o define las variables de entorno AWS_*."
        )
    if isinstance(error, EndpointConnectionError):
        return f"No fue posible conectarse a AWS ({error.kwargs.get('endpoint_url', '')}). Revisa tu red."
    if isinstance(error, ClientError):
        return _explain_client_error(error, last_action)
    raise TypeError(f"Unexpected error type: {type(error).__name__}") from error


def _explain_client_error(error: ClientError, last_action: str | None) -> str:
    details = error.response.get("Error", {})
    message = details.get("Message", "")
    if not is_access_denied(error):
        return f"Error de AWS en {error.operation_name}: {details.get('Code')} - {message}"
    match = _ACTION_IN_MESSAGE.search(message)
    action = match.group(1) if match else (last_action or error.operation_name)
    return f"Falta el permiso IAM '{action}'. {POLICY_HINT}"
