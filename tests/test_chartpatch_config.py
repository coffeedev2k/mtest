from __future__ import annotations

import re
from pathlib import Path

import pytest

from chartpatch.config import (
    ConfigError,
    load_config,
    normalize_chart_entries,
    validate_config,
)


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

MULTI_CHART_CONFIG = {
    "registry": {"url": "localhost:5000"},
    "charts": [
        VALID_CONFIG["chart"],
        {
            "name": "kyverno",
            "source": {
                "repo": "https://kyverno.github.io/kyverno",
                "chart": "kyverno",
                "version": "3.3.7",
            },
            "patch": {"file": "patches/kyverno.patch"},
            "output": {"chart_ref": "oci://localhost:5000/helm/kyverno"},
            "verification": {"helm_lint": False, "helm_template": True},
        },
    ],
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


def test_legacy_top_level_chart_config_remains_single_chart() -> None:
    config = validate_config(VALID_CONFIG)

    assert len(config.charts) == 1
    assert config.chart.name == "kube-prometheus-stack"


def test_top_level_charts_config_parses_multiple_entries_in_order() -> None:
    config = validate_config(MULTI_CHART_CONFIG)

    assert config.is_multi_chart is True
    assert tuple(chart.name for chart in config.charts) == (
        "kube-prometheus-stack",
        "kyverno",
    )
    assert config.charts[1].source.repo == "https://kyverno.github.io/kyverno"
    assert config.charts[1].verification.helm_lint is False


def test_top_level_charts_config_is_marked_plan_only_even_with_one_entry() -> None:
    raw = {"registry": {"url": "localhost:5000"}, "charts": [VALID_CONFIG["chart"]]}

    config = validate_config(raw)

    assert config.is_multi_chart is True
    assert len(config.charts) == 1


def test_legacy_single_chart_normalization_includes_flat_chart_entry() -> None:
    entries = normalize_chart_entries(validate_config(VALID_CONFIG))

    assert len(entries) == 1
    assert entries[0].chart_name == "kube-prometheus-stack"
    assert entries[0].source_repo == "https://prometheus-community.github.io/helm-charts"
    assert entries[0].source_chart == "kube-prometheus-stack"
    assert entries[0].source_version == "70.0.0"
    assert entries[0].patch_file == "patches/kube-prometheus-stack.patch"
    assert entries[0].output_chart_ref == "oci://localhost:5000/helm/kube-prometheus-stack"
    assert entries[0].helm_lint is True
    assert entries[0].helm_template is True
    assert entries[0].registry_url == "localhost:5000"


def test_multi_chart_normalization_preserves_order_and_inherits_registry() -> None:
    entries = normalize_chart_entries(validate_config(MULTI_CHART_CONFIG))

    assert tuple(entry.chart_name for entry in entries) == (
        "kube-prometheus-stack",
        "kyverno",
    )
    assert entries[0].registry_url == "localhost:5000"
    assert entries[1].registry_url == "localhost:5000"
    assert entries[1].source_repo == "https://kyverno.github.io/kyverno"
    assert entries[1].patch_file == "patches/kyverno.patch"
    assert entries[1].output_chart_ref == "oci://localhost:5000/helm/kyverno"
    assert entries[1].helm_lint is False
    assert entries[1].helm_template is True


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


@pytest.mark.parametrize("section", ["registry"])
def test_each_required_top_level_section_missing_fails_validation(section: str) -> None:
    raw = _without_field(VALID_CONFIG, section)

    with pytest.raises(ConfigError, match=f"{section} is required"):
        validate_config(raw)


def test_config_with_both_chart_and_charts_fails_validation() -> None:
    raw = _copy(VALID_CONFIG)
    raw["charts"] = [raw["chart"]]

    with pytest.raises(
        ConfigError,
        match="config must specify either chart or charts, not both",
    ):
        validate_config(raw)


def test_config_with_neither_chart_nor_charts_fails_validation() -> None:
    raw = {"registry": {"url": "localhost:5000"}}

    with pytest.raises(ConfigError, match="one of chart or charts is required"):
        validate_config(raw)


def test_empty_charts_fails_validation() -> None:
    raw = {"registry": {"url": "localhost:5000"}, "charts": []}

    with pytest.raises(ConfigError, match="charts must contain at least one chart"):
        validate_config(raw)


def test_multi_chart_item_missing_required_field_reports_index() -> None:
    raw = _copy(MULTI_CHART_CONFIG)
    del raw["charts"][1]["source"]["version"]

    with pytest.raises(
        ConfigError,
        match=r"charts\[1\]\.source\.version is required",
    ):
        validate_config(raw)


def test_multi_chart_item_missing_required_field_reports_chart_name() -> None:
    raw = _copy(MULTI_CHART_CONFIG)
    del raw["charts"][1]["patch"]

    with pytest.raises(
        ConfigError,
        match=r"charts\[1\] \(kyverno\): charts\[1\]\.patch is required",
    ):
        validate_config(raw)


def test_multi_chart_item_without_name_reports_index() -> None:
    raw = _copy(MULTI_CHART_CONFIG)
    del raw["charts"][1]["name"]

    with pytest.raises(
        ConfigError,
        match=r"charts\[1\]: charts\[1\]\.name is required",
    ):
        validate_config(raw)


def test_duplicate_multi_chart_names_fail_validation() -> None:
    raw = _copy(MULTI_CHART_CONFIG)
    raw["charts"][1]["name"] = "kube-prometheus-stack"

    with pytest.raises(
        ConfigError,
        match=r"duplicate chart name 'kube-prometheus-stack' in charts\[1\]",
    ):
        validate_config(raw)


def test_duplicate_multi_chart_output_refs_fail_validation() -> None:
    raw = _copy(MULTI_CHART_CONFIG)
    raw["charts"][1]["output"]["chart_ref"] = (
        "oci://localhost:5000/helm/kube-prometheus-stack"
    )

    with pytest.raises(
        ConfigError,
        match=(
            r"duplicate output\.chart_ref "
            r"'oci://localhost:5000/helm/kube-prometheus-stack' in charts\[1\]"
        ),
    ):
        validate_config(raw)


@pytest.mark.parametrize(
    "field",
    [
        "registry.url",
        "charts.1.name",
        "charts.1.source.repo",
        "charts.1.source.chart",
        "charts.1.source.version",
        "charts.1.patch.file",
        "charts.1.output.chart_ref",
    ],
)
def test_multi_chart_required_fields_missing_fail_validation(field: str) -> None:
    raw = _without_path(MULTI_CHART_CONFIG, field)

    with pytest.raises(
        ConfigError,
        match=re.escape(f"{_display_path(field)} is required"),
    ):
        validate_config(raw)


@pytest.mark.parametrize(
    "field",
    [
        "registry.url",
        "charts.1.name",
        "charts.1.source.repo",
        "charts.1.source.chart",
        "charts.1.source.version",
        "charts.1.patch.file",
        "charts.1.output.chart_ref",
    ],
)
def test_multi_chart_required_string_fields_empty_fail_validation(field: str) -> None:
    raw = _with_path(MULTI_CHART_CONFIG, field, "  ")

    with pytest.raises(
        ConfigError,
        match=re.escape(f"{_display_path(field)} must be a non-empty string"),
    ):
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


def test_valid_multi_chart_fixture_parses() -> None:
    config = load_config(Path("tests/fixtures/chartpatch/valid-multi-chart.yaml"))

    assert tuple(chart.name for chart in config.charts) == (
        "kube-prometheus-stack",
        "kyverno",
    )


def test_multi_chart_acceptance_fixture_parses() -> None:
    config = load_config(Path("tests/fixtures/chartpatch/multi-chart-acceptance.yaml"))

    assert tuple(chart.name for chart in config.charts) == ("alpha", "beta")
    assert tuple(chart.source.version for chart in config.charts) == ("1.0.0", "2.0.0")
    assert tuple(chart.output.chart_ref for chart in config.charts) == (
        "oci://localhost:5000/helm/alpha",
        "oci://localhost:5000/helm/beta",
    )


def test_invalid_multi_chart_acceptance_fixture_fails_validation() -> None:
    with pytest.raises(
        ConfigError,
        match=r"charts\[1\] \(beta\): charts\[1\]\.source\.version is required",
    ):
        load_config(
            Path(
                "tests/fixtures/chartpatch/"
                "invalid-multi-chart-missing-source-version.yaml"
            )
        )


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
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value


def _without_path(raw: dict[str, object], field: str) -> dict[str, object]:
    copied = _copy(raw)
    parent = _path_parent(copied, field)
    del parent[field.split(".")[-1]]
    return copied


def _with_path(
    raw: dict[str, object],
    field: str,
    value: object,
) -> dict[str, object]:
    copied = _copy(raw)
    parent = _path_parent(copied, field)
    parent[field.split(".")[-1]] = value
    return copied


def _path_parent(raw: object, field: str) -> dict[str, object]:
    parent = raw
    for part in field.split(".")[:-1]:
        if isinstance(parent, list):
            parent = parent[int(part)]
        else:
            parent = parent[part]
    return parent


def _display_path(field: str) -> str:
    return field.replace("charts.1", "charts[1]", 1)
