from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlsplit

from .runner import CommandResult, CommandRunner


def helm_pull_args(
    source_repo: str,
    source_chart: str,
    source_version: str,
    destination_dir: Path,
) -> list[str]:
    if source_repo.startswith("oci://"):
        chart_ref = f"{source_repo.rstrip('/')}/{source_chart.lstrip('/')}"
        return [
            "helm",
            "pull",
            chart_ref,
            "--version",
            source_version,
            "--destination",
            str(destination_dir),
        ]
    return [
        "helm",
        "pull",
        source_chart,
        "--repo",
        source_repo,
        "--version",
        source_version,
        "--destination",
        str(destination_dir),
    ]


def _helm_set_string_args(values: tuple[tuple[str, str], ...]) -> list[str]:
    args: list[str] = []
    for key, value in values:
        args.extend(["--set-string", f"{key}={value}"])
    return args


def helm_lint_args(
    chart_dir: Path,
    values: tuple[tuple[str, str], ...] = (),
) -> list[str]:
    return ["helm", "lint", str(chart_dir), *_helm_set_string_args(values)]


def helm_template_args(
    release_name: str,
    chart_dir: Path,
    values: tuple[tuple[str, str], ...] = (),
) -> list[str]:
    return [
        "helm",
        "template",
        release_name,
        str(chart_dir),
        *_helm_set_string_args(values),
    ]


def helm_package_args(chart_dir: Path, destination_dir: Path) -> list[str]:
    return ["helm", "package", str(chart_dir), "--destination", str(destination_dir)]


def validate_oci_chart_ref(chart_ref: str) -> None:
    if not chart_ref.startswith("oci://"):
        raise ValueError(
            "chart.output.chart_ref must start with oci:// for helm push: "
            f"{chart_ref}"
        )


def is_native_helm_repository(chart_ref: str) -> bool:
    return chart_ref.startswith(("http://", "https://"))


def chart_output_label(chart_ref: str) -> str:
    if is_native_helm_repository(chart_ref):
        return "Output native Helm repository"
    return "Output OCI chart reference"


def nexus_helm_upload_args(
    packaged_chart_path: Path,
    chart_ref: str,
    netrc_file: Path,
) -> list[str]:
    upload_url = nexus_helm_upload_url(chart_ref)
    return [
        "curl",
        "--fail",
        "--silent",
        "--show-error",
        "--netrc-file",
        str(netrc_file),
        "--request",
        "POST",
        "--form",
        f"helm.asset=@{packaged_chart_path}",
        upload_url,
    ]


def nexus_helm_upload_url(chart_ref: str) -> str:
    parsed = urlsplit(chart_ref)
    marker = "/repository/"
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "native Helm repository URL must use http:// or https://: "
            f"{chart_ref}"
        )
    if marker not in parsed.path:
        raise ValueError(
            "native Nexus Helm repository URL must contain /repository/: "
            f"{chart_ref}"
        )
    repository = parsed.path.split(marker, 1)[1].strip("/")
    if not repository or "/" in repository:
        raise ValueError(
            "native Nexus Helm repository URL must identify one repository: "
            f"{chart_ref}"
        )
    return (
        f"{parsed.scheme}://{parsed.netloc}/service/rest/v1/components"
        f"?repository={quote(repository)}"
    )


def helm_push_args(packaged_chart_path: Path, chart_ref: str) -> list[str]:
    validate_oci_chart_ref(chart_ref)
    return ["helm", "push", str(packaged_chart_path), chart_ref, "--plain-http"]


def helm_registry_login_args(
    registry: str,
    username: str,
    registry_config: Path,
) -> list[str]:
    return [
        "helm",
        "registry",
        "login",
        registry,
        "--insecure",
        "--username",
        username,
        "--password-stdin",
        "--registry-config",
        str(registry_config),
    ]


def run_helm_lint(
    runner: CommandRunner,
    chart_dir: Path,
    values: tuple[tuple[str, str], ...] = (),
) -> CommandResult:
    return runner.run(helm_lint_args(chart_dir, values))


def run_helm_pull(
    runner: CommandRunner,
    source_repo: str,
    source_chart: str,
    source_version: str,
    destination_dir: Path,
) -> CommandResult:
    return runner.run(
        helm_pull_args(
            source_repo,
            source_chart,
            source_version,
            destination_dir,
        )
    )


def run_helm_template(
    runner: CommandRunner,
    release_name: str,
    chart_dir: Path,
    values: tuple[tuple[str, str], ...] = (),
) -> CommandResult:
    return runner.run(helm_template_args(release_name, chart_dir, values))


def run_helm_package(
    runner: CommandRunner,
    chart_dir: Path,
    destination_dir: Path,
) -> CommandResult:
    return runner.run(helm_package_args(chart_dir, destination_dir))


def run_helm_push(
    runner: CommandRunner,
    packaged_chart_path: Path,
    chart_ref: str,
    *,
    registry_config: Path | None = None,
) -> CommandResult:
    args = helm_push_args(packaged_chart_path, chart_ref)
    if registry_config is not None:
        args.extend(["--registry-config", str(registry_config)])
    return runner.run(args)


def run_nexus_helm_upload(
    runner: CommandRunner,
    packaged_chart_path: Path,
    chart_ref: str,
    netrc_file: Path,
) -> CommandResult:
    return runner.run(
        nexus_helm_upload_args(
            packaged_chart_path,
            chart_ref,
            netrc_file,
        )
    )


def run_helm_registry_login(
    runner: CommandRunner,
    registry: str,
    username: str,
    password: str,
    registry_config: Path,
) -> CommandResult:
    return runner.run(
        helm_registry_login_args(registry, username, registry_config),
        input_text=f"{password}\n",
    )
