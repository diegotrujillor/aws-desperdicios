import json

from aws_desperdicios.report import Finding, RegionError, Report, render_json, render_table


def sample_report(**overrides):
    base = dict(
        title="Volúmenes gp2 que podrían ser gp3",
        findings=(
            Finding(
                region="us-east-1",
                resource_id="vol-111",
                detail="500 GiB gp2",
                monthly_savings_usd=10.0,
                savings_kind="exacto",
                suggested_command="aws ec2 modify-volume --volume-id vol-111",
            ),
            Finding(
                region="sa-east-1",
                resource_id="vol-222",
                detail="20 GiB gp2",
                monthly_savings_usd=None,
                savings_kind="exacto",
                suggested_command=None,
            ),
        ),
        errors=(
            RegionError("eu-west-1", "Falta el permiso IAM 'ec2:DescribeVolumes'."),
            RegionError("eu-west-2", "Falta el permiso IAM 'ec2:DescribeVolumes'."),
        ),
        notes=("Supuesto de ejemplo.",),
        price_sources=("AWS Pricing API (consultada 2026-11-12)",),
    )
    return Report(**{**base, **overrides})


def test_total_ignores_findings_without_price():
    assert sample_report().total_monthly_savings_usd == 10.0


def test_table_lists_findings_total_commands_and_sources():
    text = render_table(sample_report())

    assert "vol-111" in text and "vol-222" in text
    assert "10.00" in text
    assert "sin precio" in text
    assert "Total estimado: 10.00 USD/mes" in text
    assert "aws ec2 modify-volume --volume-id vol-111" in text
    assert "no se ejecutaron" in text
    assert "AWS Pricing API (consultada 2026-11-12)" in text
    assert "Supuesto de ejemplo." in text


def test_table_groups_identical_region_errors():
    text = render_table(sample_report())
    assert text.count("ec2:DescribeVolumes") == 1
    assert "eu-west-1, eu-west-2" in text


def test_table_reports_when_nothing_was_found():
    text = render_table(sample_report(findings=(), errors=()))
    assert "No se encontraron recursos" in text


def test_json_is_machine_readable_and_complete():
    data = json.loads(render_json(sample_report()))

    assert data["titulo"] == "Volúmenes gp2 que podrían ser gp3"
    assert data["total_ahorro_mensual_usd"] == 10.0
    assert data["hallazgos"][0] == {
        "region": "us-east-1",
        "recurso": "vol-111",
        "detalle": "500 GiB gp2",
        "ahorro_mensual_usd": 10.0,
        "tipo_ahorro": "exacto",
        "comando_sugerido": "aws ec2 modify-volume --volume-id vol-111",
    }
    assert data["hallazgos"][1]["ahorro_mensual_usd"] is None
    assert len(data["errores"]) == 2
    assert data["notas"] == ["Supuesto de ejemplo."]
    assert data["fuentes_de_precios"] == ["AWS Pricing API (consultada 2026-11-12)"]
