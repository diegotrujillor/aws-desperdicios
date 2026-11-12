"""Report model and renderers (terminal table and JSON). User-facing text is in Spanish."""
import json
from dataclasses import dataclass
from typing import Literal

SavingsKind = Literal["exacto", "máximo"]
NO_PRICE = "sin precio"
TABLE_HEADERS = ("Región", "Recurso", "Detalle", "Ahorro USD/mes", "Tipo")


@dataclass(frozen=True)
class Finding:
    region: str
    resource_id: str
    detail: str
    monthly_savings_usd: float | None
    savings_kind: SavingsKind
    suggested_command: str | None


@dataclass(frozen=True)
class RegionError:
    region: str
    message: str


@dataclass(frozen=True)
class Report:
    title: str
    findings: tuple[Finding, ...]
    errors: tuple[RegionError, ...]
    notes: tuple[str, ...]
    price_sources: tuple[str, ...]

    @property
    def total_monthly_savings_usd(self) -> float:
        return round(sum(f.monthly_savings_usd or 0.0 for f in self.findings), 2)


def render_json(report: Report) -> str:
    payload = {
        "titulo": report.title,
        "total_ahorro_mensual_usd": report.total_monthly_savings_usd,
        "hallazgos": [
            {
                "region": f.region,
                "recurso": f.resource_id,
                "detalle": f.detail,
                "ahorro_mensual_usd": f.monthly_savings_usd,
                "tipo_ahorro": f.savings_kind,
                "comando_sugerido": f.suggested_command,
            }
            for f in report.findings
        ],
        "errores": [{"region": e.region, "mensaje": e.message} for e in report.errors],
        "notas": list(report.notes),
        "fuentes_de_precios": list(report.price_sources),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_table(report: Report) -> str:
    sections = [f"{report.title}\n{'=' * len(report.title)}", _findings_section(report)]
    sections += _optional_sections(report)
    return "\n\n".join(sections) + "\n"


def _findings_section(report: Report) -> str:
    if not report.findings:
        return "No se encontraron recursos con este desperdicio en las regiones revisadas."
    rows = [
        (f.region, f.resource_id, f.detail, _money(f.monthly_savings_usd), f.savings_kind)
        for f in report.findings
    ]
    total = f"Total estimado: {report.total_monthly_savings_usd:.2f} USD/mes"
    return f"{_format_table(TABLE_HEADERS, rows)}\n\n{total}"


def _optional_sections(report: Report) -> list[str]:
    sections = []
    commands = [f.suggested_command for f in report.findings if f.suggested_command]
    if commands:
        sections.append(
            "Comandos sugeridos (no se ejecutaron; revísalos antes de usarlos):\n"
            + "\n".join(f"  {c}" for c in commands)
        )
    if report.errors:
        sections.append("Errores:\n" + "\n".join(f"  {line}" for line in _grouped_errors(report.errors)))
    if report.notes:
        sections.append("Notas:\n" + "\n".join(f"  - {n}" for n in report.notes))
    if report.price_sources:
        sections.append("Fuentes de precios:\n" + "\n".join(f"  - {s}" for s in report.price_sources))
    return sections


def _grouped_errors(errors: tuple[RegionError, ...]) -> list[str]:
    regions_by_message: dict[str, list[str]] = {}
    for error in errors:
        regions_by_message.setdefault(error.message, []).append(error.region)
    return [f"[{', '.join(regions)}] {message}" for message, regions in regions_by_message.items()]


def _money(value: float | None) -> str:
    return NO_PRICE if value is None else f"{value:.2f}"


def _format_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> str:
    widths = [max(len(str(cell)) for cell in column) for column in zip(headers, *rows)]

    def line(cells):
        return "  ".join(str(cell).ljust(width) for cell, width in zip(cells, widths)).rstrip()

    separator = "  ".join("-" * width for width in widths)
    return "\n".join([line(headers), separator, *(line(row) for row in rows)])
