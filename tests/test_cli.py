import json

import pytest
from botocore.exceptions import ClientError, NoCredentialsError

from aws_desperdicios.cli import CheckDefinition, run_check
from aws_desperdicios.report import Finding


def finding(region):
    return Finding(
        region=region,
        resource_id=f"res-{region}",
        detail="detalle",
        monthly_savings_usd=1.5,
        savings_kind="máximo",
    )


def make_check(scan, notes=lambda args: ("Nota del chequeo.",)):
    return CheckDefinition(title="Chequeo de prueba", description="desc", scan=scan, notes=notes)


@pytest.fixture
def ok_check():
    return make_check(lambda session, region, prices, args: [finding(region)])


def test_prints_table_for_requested_region(aws, ok_check, capsys):
    code = run_check(ok_check, ["--region", "sa-east-1", "--precios-locales"])

    out = capsys.readouterr().out
    assert code == 0
    assert "Chequeo de prueba" in out and "res-sa-east-1" in out
    assert "Nota del chequeo." in out


def test_json_flag_outputs_json(aws, ok_check, capsys):
    code = run_check(ok_check, ["--region", "us-east-1", "--json", "--precios-locales"])

    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["hallazgos"][0]["recurso"] == "res-us-east-1"
    assert data["total_ahorro_mensual_usd"] == 1.5


def test_scans_all_enabled_regions_when_no_region_given(aws, ok_check, capsys):
    run_check(ok_check, ["--json", "--precios-locales"])

    regions = {f["region"] for f in json.loads(capsys.readouterr().out)["hallazgos"]}
    assert {"us-east-1", "sa-east-1"} <= regions


def test_access_denied_in_a_region_is_reported_and_exit_code_is_1(aws, capsys):
    def scan(session, region, prices, args):
        raise ClientError({"Error": {"Code": "UnauthorizedOperation", "Message": ""}}, "DescribeVolumes")

    code = run_check(make_check(scan), ["--region", "us-east-1", "--precios-locales"])

    out = capsys.readouterr().out
    assert code == 1
    assert "Falta el permiso IAM" in out


def test_last_called_action_is_used_when_aws_message_has_none(aws, capsys):
    def scan(session, region, prices, args):
        session.client("ec2", region_name=region).describe_volumes()
        raise ClientError({"Error": {"Code": "UnauthorizedOperation", "Message": ""}}, "DescribeVolumes")

    run_check(make_check(scan), ["--region", "us-east-1", "--precios-locales"])

    assert "'ec2:DescribeVolumes'" in capsys.readouterr().out


def test_missing_credentials_is_fatal_with_exit_code_2(aws, capsys):
    def scan(session, region, prices, args):
        raise NoCredentialsError()

    code = run_check(make_check(scan), ["--region", "us-east-1", "--precios-locales"])

    assert code == 2
    assert "No se encontraron credenciales" in capsys.readouterr().err


def test_unknown_profile_is_fatal_with_exit_code_2(ok_check, capsys):
    code = run_check(ok_check, ["--profile", "no-existe", "--region", "us-east-1"])

    assert code == 2
    assert "perfil 'no-existe'" in capsys.readouterr().err


def test_local_prices_flag_disables_pricing_api(aws, capsys):
    seen = {}

    def scan(session, region, prices, args):
        seen["uses_api"] = prices.uses_api
        return []

    run_check(make_check(scan), ["--region", "us-east-1", "--precios-locales"])
    assert seen["uses_api"] is False


def test_pricing_api_is_used_by_default(aws, capsys):
    seen = {}

    def scan(session, region, prices, args):
        seen["uses_api"] = prices.uses_api
        return []

    run_check(make_check(scan), ["--region", "us-east-1"])
    assert seen["uses_api"] is True


def test_custom_price_table_path_that_does_not_exist_is_fatal(aws, ok_check, capsys, tmp_path):
    code = run_check(ok_check, ["--region", "us-east-1", "--precios", str(tmp_path / "x.toml")])

    assert code == 2
    assert "tabla de precios" in capsys.readouterr().err


def test_denied_region_discovery_is_fatal_and_suggests_region_flag(aws, ok_check, capsys, monkeypatch):
    def deny(session, region):
        raise ClientError({"Error": {"Code": "UnauthorizedOperation", "Message": ""}}, "DescribeRegions")

    monkeypatch.setattr("aws_desperdicios.cli.resolve_regions", deny)

    code = run_check(ok_check, ["--precios-locales"])

    err = capsys.readouterr().err
    assert code == 2
    assert "Falta el permiso IAM" in err and "--region" in err
