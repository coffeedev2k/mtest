from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(ValueError):
    """Raised when a chartpatch config cannot be loaded or validated."""


@dataclass(frozen=True)
class SourceConfig:
    repo: str
    chart: str
    version: str


@dataclass(frozen=True)
class PatchConfig:
    file: str


@dataclass(frozen=True)
class OutputConfig:
    chart_ref: str


@dataclass(frozen=True)
class VerificationConfig:
    helm_lint: bool = False
    helm_template: bool = False


@dataclass(frozen=True)
class ChartConfig:
    name: str
    source: SourceConfig
    patch: PatchConfig
    output: OutputConfig
    verification: VerificationConfig
    values: tuple[tuple[str, str], ...] = ()
    image_overrides: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class RegistryConfig:
    url: str
    username: str | None = None
    password: str | None = None


@dataclass(frozen=True)
class NormalizedChartConfig:
    chart_name: str
    source_repo: str
    source_chart: str
    source_version: str
    patch_file: str
    output_chart_ref: str
    helm_lint: bool
    helm_template: bool
    registry_url: str
    registry_username: str | None = None
    registry_password: str | None = None
    helm_values: tuple[tuple[str, str], ...] = ()
    image_overrides: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ChartPatchConfig:
    registry: RegistryConfig
    charts: tuple[ChartConfig, ...]
    uses_charts_list: bool = False

    @property
    def chart(self) -> ChartConfig:
        if len(self.charts) != 1:
            raise ConfigError("multi-chart config does not have a single chart")
        return self.charts[0]

    @property
    def is_multi_chart(self) -> bool:
        return self.uses_charts_list


def load_config(path: Path) -> ChartPatchConfig:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"config file not found: {path}") from None
    except OSError as exc:
        raise ConfigError(f"could not read config file {path}: {exc}") from None

    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from None

    return validate_config(raw)


def validate_config(raw: Any) -> ChartPatchConfig:
    if not isinstance(raw, dict):
        raise ConfigError("config must be a YAML mapping")

    registry = _required_mapping(raw, "registry")
    registry_url = _required_string(registry, "registry.url")
    registry_username = _optional_string(registry, "username", "registry.username")
    registry_password = _optional_string(registry, "password", "registry.password")
    if (registry_username is None) != (registry_password is None):
        raise ConfigError(
            "registry.username and registry.password must be configured together"
        )

    has_chart = "chart" in raw
    has_charts = "charts" in raw
    if has_chart and has_charts:
        raise ConfigError("config must specify either chart or charts, not both")
    if not has_chart and not has_charts:
        raise ConfigError("one of chart or charts is required")

    if has_chart:
        chart = _required_mapping(raw, "chart")
        charts = (_validate_single_chart_config(chart),)
    else:
        charts_value = raw["charts"]
        if not isinstance(charts_value, list):
            raise ConfigError("charts must be a list")
        if not charts_value:
            raise ConfigError("charts must contain at least one chart")
        charts = tuple(
            _validate_chart_entry(item, index)
            for index, item in enumerate(charts_value)
        )
        _reject_duplicate_chart_names(charts)
        _reject_duplicate_output_chart_refs(charts)

    return ChartPatchConfig(
        registry=RegistryConfig(
            url=registry_url,
            username=registry_username,
            password=registry_password,
        ),
        charts=charts,
        uses_charts_list=has_charts,
    )


def normalize_chart_entries(config: ChartPatchConfig) -> tuple[NormalizedChartConfig, ...]:
    return tuple(
        NormalizedChartConfig(
            chart_name=chart.name,
            source_repo=chart.source.repo,
            source_chart=chart.source.chart,
            source_version=chart.source.version,
            patch_file=chart.patch.file,
            output_chart_ref=chart.output.chart_ref,
            helm_lint=chart.verification.helm_lint,
            helm_template=chart.verification.helm_template,
            registry_url=config.registry.url,
            registry_username=config.registry.username,
            registry_password=config.registry.password,
            helm_values=chart.values,
            image_overrides=chart.image_overrides,
        )
        for chart in config.charts
    )


def _validate_chart_entry(raw: Any, index: int) -> ChartConfig:
    path = f"charts[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must be a mapping")
    try:
        return _validate_chart_config(raw, path)
    except ConfigError as exc:
        raise ConfigError(f"{_chart_context(raw, index)}: {exc}") from None


def _validate_single_chart_config(raw: dict[str, Any]) -> ChartConfig:
    try:
        return _validate_chart_config(raw, "chart")
    except ConfigError as exc:
        raise ConfigError(f"{_single_chart_context(raw)}: {exc}") from None


def _validate_chart_config(chart: dict[str, Any], path: str) -> ChartConfig:
    source = _required_mapping(chart, f"{path}.source")
    patch = _required_mapping(chart, f"{path}.patch")
    output = _required_mapping(chart, f"{path}.output")
    verification = _required_mapping(chart, f"{path}.verification")
    chart_ref = _required_string(output, f"{path}.output.chart_ref")

    return ChartConfig(
        name=_required_string(chart, f"{path}.name"),
        source=SourceConfig(
            repo=_required_string(source, f"{path}.source.repo"),
            chart=_required_string(source, f"{path}.source.chart"),
            version=_required_string(source, f"{path}.source.version"),
        ),
        patch=PatchConfig(file=_required_string(patch, f"{path}.patch.file")),
        output=OutputConfig(chart_ref=chart_ref),
        verification=VerificationConfig(
            helm_lint=_required_bool(
                verification,
                "helm_lint",
                f"{path}.verification.helm_lint",
            ),
            helm_template=_required_bool(
                verification,
                "helm_template",
                f"{path}.verification.helm_template",
            ),
        ),
        values=_optional_values(chart, path),
        image_overrides=_optional_string_mapping(
            chart,
            "image_overrides",
            f"{path}.image_overrides",
        ),
    )


def _required_mapping(data: dict[str, Any], path: str) -> dict[str, Any]:
    key = path.rsplit(".", 1)[-1]
    if key not in data:
        raise ConfigError(f"{path} is required")
    value = data[key]
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must be a mapping")
    return value


def _required_string(data: dict[str, Any], path: str) -> str:
    key = path.rsplit(".", 1)[-1]
    if key not in data:
        raise ConfigError(f"{path} is required")
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path} must be a non-empty string")
    return value.strip()


def _required_bool(data: dict[str, Any], key: str, path: str) -> bool:
    if key not in data:
        raise ConfigError(f"{path} is required")
    value = data[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{path} must be a boolean")
    return value


def _optional_string(
    data: dict[str, Any],
    key: str,
    path: str,
) -> str | None:
    if key not in data:
        return None
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{path} must be a non-empty string")
    return value.strip()


def _optional_values(
    chart: dict[str, Any],
    path: str,
) -> tuple[tuple[str, str], ...]:
    if "values" not in chart:
        return ()
    values = chart["values"]
    if not isinstance(values, dict):
        raise ConfigError(f"{path}.values must be a mapping")

    normalized: list[tuple[str, str]] = []
    for key, value in values.items():
        if not isinstance(key, str) or not key.strip():
            raise ConfigError(f"{path}.values keys must be non-empty strings")
        if not isinstance(value, (str, int, float, bool)):
            raise ConfigError(
                f"{path}.values.{key} must be a string, number, or boolean"
            )
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        normalized.append((key.strip(), rendered))
    return tuple(normalized)


def _optional_string_mapping(
    data: dict[str, Any],
    key: str,
    path: str,
) -> tuple[tuple[str, str], ...]:
    if key not in data:
        return ()
    mapping = data[key]
    if not isinstance(mapping, dict):
        raise ConfigError(f"{path} must be a mapping")
    normalized: list[tuple[str, str]] = []
    for source, replacement in mapping.items():
        if not isinstance(source, str) or not source.strip():
            raise ConfigError(f"{path} keys must be non-empty strings")
        if not isinstance(replacement, str) or not replacement.strip():
            raise ConfigError(f"{path}.{source} must be a non-empty string")
        normalized.append((source.strip(), replacement.strip()))
    return tuple(normalized)


def _chart_context(raw: dict[str, Any], index: int) -> str:
    name = raw.get("name")
    if isinstance(name, str) and name.strip():
        return f"charts[{index}] ({name.strip()})"
    return f"charts[{index}]"


def _single_chart_context(raw: dict[str, Any]) -> str:
    name = raw.get("name")
    if isinstance(name, str) and name.strip():
        return f"chart ({name.strip()})"
    return "chart"


def _reject_duplicate_chart_names(charts: tuple[ChartConfig, ...]) -> None:
    seen: dict[str, int] = {}
    for index, chart in enumerate(charts):
        if chart.name in seen:
            raise ConfigError(
                f"duplicate chart name {chart.name!r} in charts[{index}]; "
                f"first defined in charts[{seen[chart.name]}]"
            )
        seen[chart.name] = index


def _reject_duplicate_output_chart_refs(charts: tuple[ChartConfig, ...]) -> None:
    seen: dict[str, int] = {}
    for index, chart in enumerate(charts):
        chart_ref = chart.output.chart_ref
        if chart_ref in seen:
            raise ConfigError(
                f"duplicate output.chart_ref {chart_ref!r} in charts[{index}] "
                f"({chart.name}); first defined in charts[{seen[chart_ref]}]"
            )
        seen[chart_ref] = index
