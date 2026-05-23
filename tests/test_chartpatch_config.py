from __future__ import annotations

from pathlib import Path

import pytest

from chartpatch.config import ConfigError, load_config, validate_config


VALID_CONFIG = {
    "registry": {"url": "localhost:5000"},
    "chart": {
        "name": "kube-prometheus-stack",
        "source": {
            "repo": "https://prometheus-community.github.io/helm-charts",
            "chart": "kube-prometheus-stack",
            "version": "70.0.0",
        },
        "patch": {"file": "patches/kube-prometheus-stack.patch"},
        "output": {"chart_ref": "oci://localhost:5000/helm/kube-prometheus-stack"},
        "verification": {"helm_lint": True, "helm_template": True},
    },
}


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("registry.url", "localhost:5000"),
        ("chart.name", "kube-prometheus-stack"),
        ("chart.source.repo", "https://prometheus-community.github.io/helm-charts"),
        ("chart.source.chart", "kube-prometheus-stack"),
        ("chart.source.version", "70.0.0"),
        ("chart.patch.file", "patches/kube-prometheus-stack.patch"),
        ("chart.output.chart_ref", "oci://localhost:5000/helm/kube-prometheus-stack"),
    ],
)
def test_valid_yaml_parses_successfully(path: str, expected: str) -> None:
    config = validate_config(VALID_CONFIG)

    value: object = config
    for part in path.split("."):
        value = getattr(value, part)

    assert value == expected


def test_missing_file_returns_clean_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(tmp_path / "missing.yaml")


def test_invalid_yaml_returns_clean_error(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("chart:\n  source: [broken\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(path)


@pytest.mark.parametrize("raw", [None, [], ""])
def test_empty_or_non_mapping_config_fails_validation(raw: object) -> None:
    with pytest.raises(ConfigError, match="config must be a YAML mapping"):
        validate_config(raw)


@pytest.mark.parametrize(
    "field",
    [
        "registry.url",
        "chart.name",
        "chart.source.repo",
        "chart.source.chart",
        "chart.source.version",
        "chart.patch.file",
        "chart.output.chart_ref",
        "chart.verification.helm_lint",
        "chart.verification.helm_template",
    ],
)
def test_each_required_field_missing_fails_validation(field: str) -> None:
    raw = _without_field(VALID_CONFIG, field)

    with pytest.raises(ConfigError, match=f"{field} is required"):
        validate_config(raw)


@pytest.mark.parametrize("section", ["registry", "chart"])
def test_each_required_top_level_section_missing_fails_validation(section: str) -> None:
    raw = _without_field(VALID_CONFIG, section)

    with pytest.raises(ConfigError, match=f"{section} is required"):
        validate_config(raw)


@pytest.mark.parametrize(
    "section",
    [
        "chart.source",
        "chart.patch",
        "chart.output",
        "chart.verification",
    ],
)
def test_each_required_nested_section_missing_fails_validation(section: str) -> None:
    raw = _without_field(VALID_CONFIG, section)

    with pytest.raises(ConfigError, match=f"{section} is required"):
        validate_config(raw)


@pytest.mark.parametrize(
    "field",
    [
        "registry.url",
        "chart.name",
        "chart.source.repo",
        "chart.source.chart",
        "chart.source.version",
        "chart.patch.file",
        "chart.output.chart_ref",
        "chart.verification.helm_lint",
        "chart.verification.helm_template",
    ],
)
def test_required_fields_with_wrong_types_fail_validation(field: str) -> None:
    raw = _with_field(VALID_CONFIG, field, 123)

    expected = (
        f"{field} must be a boolean"
        if field.startswith("chart.verification.")
        else f"{field} must be a non-empty string"
    )
    with pytest.raises(ConfigError, match=expected):
        validate_config(raw)


@pytest.mark.parametrize(
    "field",
    [
        "registry.url",
        "chart.name",
        "chart.source.repo",
        "chart.source.chart",
        "chart.source.version",
        "chart.patch.file",
        "chart.output.chart_ref",
    ],
)
def test_required_fields_with_empty_strings_fail_validation(field: str) -> None:
    raw = _with_field(VALID_CONFIG, field, "  ")

    with pytest.raises(ConfigError, match=f"{field} must be a non-empty string"):
        validate_config(raw)


def test_helm_lint_with_non_boolean_value_fails_validation() -> None:
    raw = _with_field(VALID_CONFIG, "chart.verification.helm_lint", "true")

    with pytest.raises(ConfigError, match="chart.verification.helm_lint must be a boolean"):
        validate_config(raw)


def test_helm_template_with_non_boolean_value_fails_validation() -> None:
    raw = _with_field(VALID_CONFIG, "chart.verification.helm_template", "false")

    with pytest.raises(ConfigError, match="chart.verification.helm_template must be a boolean"):
        validate_config(raw)


@pytest.mark.parametrize(
    ("fixture", "message"),
    [
        ("missing-registry.yaml", "registry is required"),
        ("missing-source.yaml", "chart.source is required"),
        ("missing-patch.yaml", "chart.patch is required"),
        ("missing-output.yaml", "chart.output is required"),
        ("missing-verification.yaml", "chart.verification is required"),
        ("missing-source-version.yaml", "chart.source.version is required"),
    ],
)
def test_invalid_regression_fixtures_fail(fixture: str, message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config(Path("tests/fixtures/chartpatch") / fixture)


def test_valid_regression_fixture_parses() -> None:
    config = load_config(Path("tests/fixtures/chartpatch/valid-kube-prometheus-stack.yaml"))

    assert config.chart.source.version == "70.0.0"
    assert config.chart.verification.helm_lint is True
    assert config.chart.verification.helm_template is True


def _without_field(raw: dict[str, object], field: str) -> dict[str, object]:
    copied = _copy(raw)
    parent = copied
    parts = field.split(".")
    for part in parts[:-1]:
        parent = parent[part]
    del parent[parts[-1]]
    return copied


def _with_field(raw: dict[str, object], field: str, value: object) -> dict[str, object]:
    copied = _copy(raw)
    parent = copied
    parts = field.split(".")
    for part in parts[:-1]:
        parent = parent[part]
    parent[parts[-1]] = value
    return copied


def _copy(value: object) -> object:
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    return value
