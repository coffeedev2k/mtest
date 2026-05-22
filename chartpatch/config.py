from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


@dataclass(frozen=True)
class RegistryConfig:
    url: str


@dataclass(frozen=True)
class ChartPatchConfig:
    registry: RegistryConfig
    chart: ChartConfig


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
    chart = _required_mapping(raw, "chart")
    source = _required_mapping(chart, "chart.source")
    patch = _required_mapping(chart, "chart.patch")
    output = _required_mapping(chart, "chart.output")
    verification = chart.get("verification", {})
    if not isinstance(verification, dict):
        raise ConfigError("chart.verification must be a mapping")

    registry_url = _required_string(registry, "registry.url")
    chart_ref = _required_string(output, "chart.output.chart_ref")
    if not chart_ref.startswith("oci://"):
        raise ConfigError("chart.output.chart_ref must start with oci://")

    authority = urlparse(chart_ref).netloc
    if registry_url != authority:
        raise ConfigError(
            "registry.url must match the registry authority in chart.output.chart_ref"
        )

    return ChartPatchConfig(
        registry=RegistryConfig(url=registry_url),
        chart=ChartConfig(
            name=_required_string(chart, "chart.name"),
            source=SourceConfig(
                repo=_required_string(source, "chart.source.repo"),
                chart=_required_string(source, "chart.source.chart"),
                version=_required_string(source, "chart.source.version"),
            ),
            patch=PatchConfig(file=_required_string(patch, "chart.patch.file")),
            output=OutputConfig(chart_ref=chart_ref),
            verification=VerificationConfig(
                helm_lint=_optional_bool(verification, "helm_lint", "chart.verification.helm_lint"),
                helm_template=_optional_bool(
                    verification,
                    "helm_template",
                    "chart.verification.helm_template",
                ),
            ),
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


def _optional_bool(data: dict[str, Any], key: str, path: str) -> bool:
    if key not in data:
        return False
    value = data[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{path} must be a boolean")
    return value

