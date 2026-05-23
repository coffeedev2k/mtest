from __future__ import annotations

from pathlib import Path
import tarfile

import pytest

from chartpatch.config import validate_config
from chartpatch.images import ImageTargetMapping
from chartpatch.runner import CommandResult
from chartpatch.workflow import SyncWorkflowError, render_sync_report, run_sync


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

ORIGINAL_RENDER_WITH_IMAGES = """apiVersion: apps/v1
kind: Deployment
spec:
  template:
    spec:
      initContainers:
        - name: setup
          image: registry.example.com/setup:1.0.0
      containers:
        - name: app
          image: docker.io/bitnami/nginx:1.27.4
"""


class StubRunner:
    def __init__(
        self,
        tmp_path: Path,
        *,
        pull_result: CommandResult | None = None,
        template_result: CommandResult | None = None,
        skopeo_results: tuple[CommandResult, ...] = (),
        create_archive: bool = True,
        extra_archive: bool = False,
        archive_chart_dir: str = "kube-prometheus-stack",
    ) -> None:
        self.tmp_path = tmp_path
        self.pull_result = pull_result
        self.template_result = template_result
        self.skopeo_results = list(skopeo_results)
        self.create_archive = create_archive
        self.extra_archive = extra_archive
        self.archive_chart_dir = archive_chart_dir
        self.calls: list[tuple[str, ...]] = []

    def run(self, args: list[str]) -> CommandResult:
        call = tuple(args)
        self.calls.append(call)
        if args[:2] == ["helm", "pull"]:
            destination = Path(args[args.index("--destination") + 1])
            if self.create_archive:
                _write_chart_archive(
                    destination / "kube-prometheus-stack-70.0.0.tgz",
                    self.tmp_path,
                    self.archive_chart_dir,
                )
            if self.extra_archive:
                _write_chart_archive(
                    destination / "extra-1.0.0.tgz",
                    self.tmp_path,
                    "extra",
                )
            return self.pull_result or CommandResult(call, 0, "pulled\n", "")
        if args[:2] == ["helm", "template"]:
            return self.template_result or CommandResult(
                call,
                0,
                ORIGINAL_RENDER_WITH_IMAGES,
                "",
            )
        if args[:2] == ["skopeo", "copy"]:
            if self.skopeo_results:
                return self.skopeo_results.pop(0)
            return CommandResult(call, 0, "copied\n", "")
        raise AssertionError(f"unexpected command: {args}")


def test_sync_creates_workspace_pulls_unpacks_renders_and_reports(tmp_path: Path) -> None:
    config = validate_config(VALID_CONFIG)
    runner = StubRunner(tmp_path)

    result = run_sync(config, repo_root=tmp_path, runner=runner)

    assert result.workspace_path.parent == tmp_path / "tmp"
    assert result.workspace_path.name.startswith("chartpatch-sync-")
    assert result.chart_archive_path == (
        result.workspace_path / "downloaded" / "kube-prometheus-stack-70.0.0.tgz"
    )
    assert result.unpacked_chart_path == (
        result.workspace_path / "unpacked" / "kube-prometheus-stack"
    )
    assert result.original_render_path == result.workspace_path / "rendered" / "original.yaml"
    assert result.original_render_path.read_text(encoding="utf-8") == ORIGINAL_RENDER_WITH_IMAGES
    assert result.discovered_images == (
        "docker.io/bitnami/nginx:1.27.4",
        "registry.example.com/setup:1.0.0",
    )
    assert result.image_target_mappings == (
        ImageTargetMapping(
            source="docker.io/bitnami/nginx:1.27.4",
            target="localhost:5000/docker.io/bitnami/nginx:1.27.4",
        ),
        ImageTargetMapping(
            source="registry.example.com/setup:1.0.0",
            target="localhost:5000/registry.example.com/setup:1.0.0",
        ),
    )
    assert tuple((image.source, image.target) for image in result.mirrored_images) == (
        (
            "docker.io/bitnami/nginx:1.27.4",
            "localhost:5000/docker.io/bitnami/nginx:1.27.4",
        ),
        (
            "registry.example.com/setup:1.0.0",
            "localhost:5000/registry.example.com/setup:1.0.0",
        ),
    )
    assert [call[:2] for call in runner.calls] == [
        ("helm", "pull"),
        ("helm", "template"),
        ("skopeo", "copy"),
        ("skopeo", "copy"),
    ]
    assert all(
        call[:2]
        not in {
            ("git", "apply"),
            ("helm", "lint"),
            ("helm", "package"),
            ("helm", "push"),
        }
        for call in runner.calls
    )

    pull_args = runner.calls[0]
    assert pull_args == (
        "helm",
        "pull",
        "kube-prometheus-stack",
        "--repo",
        "https://prometheus-community.github.io/helm-charts",
        "--version",
        "70.0.0",
        "--destination",
        str(result.workspace_path / "downloaded"),
    )
    template_args = runner.calls[1]
    assert template_args == (
        "helm",
        "template",
        "kube-prometheus-stack",
        str(result.unpacked_chart_path),
    )
    assert runner.calls[2] == (
        "skopeo",
        "copy",
        "docker://docker.io/bitnami/nginx:1.27.4",
        "docker://localhost:5000/docker.io/bitnami/nginx:1.27.4",
    )
    assert runner.calls[3] == (
        "skopeo",
        "copy",
        "docker://registry.example.com/setup:1.0.0",
        "docker://localhost:5000/registry.example.com/setup:1.0.0",
    )

    report = render_sync_report(result)
    assert "Source chart repo: https://prometheus-community.github.io/helm-charts" in report
    assert "Source chart name: kube-prometheus-stack" in report
    assert "Source chart version: 70.0.0" in report
    assert f"Workspace path: {result.workspace_path}" in report
    assert f"Pulled chart archive: {result.chart_archive_path}" in report
    assert f"Unpacked chart path: {result.unpacked_chart_path}" in report
    assert f"Original render output: {result.original_render_path}" in report
    assert "Discovered images: 2" in report
    assert "  - docker.io/bitnami/nginx:1.27.4" in report
    assert "  - registry.example.com/setup:1.0.0" in report
    assert "Image target mappings: 2" in report
    assert (
        "  - docker.io/bitnami/nginx:1.27.4 -> "
        "localhost:5000/docker.io/bitnami/nginx:1.27.4"
    ) in report
    assert (
        "  - registry.example.com/setup:1.0.0 -> "
        "localhost:5000/registry.example.com/setup:1.0.0"
    ) in report
    assert "Mirrored images: 2" in report
    assert (
        "  - docker.io/bitnami/nginx:1.27.4 -> "
        "localhost:5000/docker.io/bitnami/nginx:1.27.4"
    ) in report
    assert (
        "  - registry.example.com/setup:1.0.0 -> "
        "localhost:5000/registry.example.com/setup:1.0.0"
    ) in report
    assert report.index("Discovered images: 2") < report.index("Image target mappings: 2")
    assert report.index("Image target mappings: 2") < report.index("Mirrored images: 2")


def test_sync_logs_command_output(tmp_path: Path) -> None:
    result = run_sync(validate_config(VALID_CONFIG), repo_root=tmp_path, runner=StubRunner(tmp_path))

    logs_dir = result.workspace_path / "logs"
    assert (logs_dir / "helm-pull.stdout.txt").read_text(encoding="utf-8") == "pulled\n"
    assert "helm pull kube-prometheus-stack" in (
        logs_dir / "helm-pull.args.txt"
    ).read_text(encoding="utf-8")
    assert "helm template kube-prometheus-stack" in (
        logs_dir / "helm-template-original.args.txt"
    ).read_text(encoding="utf-8")
    assert "skopeo copy docker://docker.io/bitnami/nginx:1.27.4" in (
        logs_dir / "skopeo-copy-1.args.txt"
    ).read_text(encoding="utf-8")


def test_sync_fails_when_helm_pull_fails(tmp_path: Path) -> None:
    runner = StubRunner(
        tmp_path,
        pull_result=CommandResult(
            ("helm", "pull"),
            23,
            "pull stdout\n",
            "pull stderr\n",
        ),
    )

    with pytest.raises(SyncWorkflowError) as exc_info:
        run_sync(validate_config(VALID_CONFIG), repo_root=tmp_path, runner=runner)

    message = str(exc_info.value)
    assert "helm pull failed" in message
    assert "exited with code 23" in message
    assert "pull stdout" in message
    assert "pull stderr" in message
    assert [call[:2] for call in runner.calls] == [("helm", "pull")]


def test_sync_fails_when_helm_template_fails(tmp_path: Path) -> None:
    runner = StubRunner(
        tmp_path,
        template_result=CommandResult(
            ("helm", "template"),
            42,
            "template stdout\n",
            "template stderr\n",
        ),
    )

    with pytest.raises(SyncWorkflowError) as exc_info:
        run_sync(validate_config(VALID_CONFIG), repo_root=tmp_path, runner=runner)

    message = str(exc_info.value)
    assert "helm template failed" in message
    assert "exited with code 42" in message
    assert "template stdout" in message
    assert "template stderr" in message
    assert [call[:2] for call in runner.calls] == [
        ("helm", "pull"),
        ("helm", "template"),
    ]


def test_sync_fails_when_skopeo_copy_fails_and_skips_later_images(tmp_path: Path) -> None:
    failed_copy = CommandResult(
        (
            "skopeo",
            "copy",
            "docker://docker.io/bitnami/nginx:1.27.4",
            "docker://localhost:5000/docker.io/bitnami/nginx:1.27.4",
        ),
        9,
        "copy stdout\n",
        "copy stderr\n",
    )
    runner = StubRunner(tmp_path, skopeo_results=(failed_copy,))

    with pytest.raises(SyncWorkflowError) as exc_info:
        run_sync(validate_config(VALID_CONFIG), repo_root=tmp_path, runner=runner)

    message = str(exc_info.value)
    assert "image mirror failed" in message
    assert "source image: docker.io/bitnami/nginx:1.27.4" in message
    assert "target image: localhost:5000/docker.io/bitnami/nginx:1.27.4" in message
    assert (
        "command: skopeo copy docker://docker.io/bitnami/nginx:1.27.4 "
        "docker://localhost:5000/docker.io/bitnami/nginx:1.27.4"
    ) in message
    assert "exit status: 9" in message
    assert "copy stdout" in message
    assert "copy stderr" in message
    assert [call[:2] for call in runner.calls] == [
        ("helm", "pull"),
        ("helm", "template"),
        ("skopeo", "copy"),
    ]


def test_sync_fails_when_original_render_contains_no_images(tmp_path: Path) -> None:
    runner = StubRunner(
        tmp_path,
        template_result=CommandResult(
            ("helm", "template"),
            0,
            "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: settings\n",
            "",
        ),
    )

    with pytest.raises(SyncWorkflowError) as exc_info:
        run_sync(validate_config(VALID_CONFIG), repo_root=tmp_path, runner=runner)

    message = str(exc_info.value)
    assert "image discovery failed" in message
    assert "no discoverable container images" in message
    assert [call[:2] for call in runner.calls] == [
        ("helm", "pull"),
        ("helm", "template"),
    ]


def test_sync_fails_when_downloaded_archive_is_missing(tmp_path: Path) -> None:
    runner = StubRunner(tmp_path, create_archive=False)

    with pytest.raises(SyncWorkflowError) as exc_info:
        run_sync(validate_config(VALID_CONFIG), repo_root=tmp_path, runner=runner)

    assert "missing downloaded chart archive" in str(exc_info.value)


def test_sync_fails_when_downloaded_archive_is_ambiguous(tmp_path: Path) -> None:
    runner = StubRunner(tmp_path, extra_archive=True)

    with pytest.raises(SyncWorkflowError) as exc_info:
        run_sync(validate_config(VALID_CONFIG), repo_root=tmp_path, runner=runner)

    assert "ambiguous downloaded chart archives" in str(exc_info.value)


def test_sync_fails_when_unpacked_chart_directory_is_missing(tmp_path: Path) -> None:
    runner = StubRunner(tmp_path, archive_chart_dir="different-chart")

    with pytest.raises(SyncWorkflowError) as exc_info:
        run_sync(validate_config(VALID_CONFIG), repo_root=tmp_path, runner=runner)

    assert "missing expected unpacked chart directory" in str(exc_info.value)


def test_sync_fails_when_unpacking_archive_fails(tmp_path: Path) -> None:
    class BadArchiveRunner(StubRunner):
        def run(self, args: list[str]) -> CommandResult:
            call = tuple(args)
            self.calls.append(call)
            if args[:2] == ["helm", "pull"]:
                destination = Path(args[args.index("--destination") + 1])
                (destination / "kube-prometheus-stack-70.0.0.tgz").write_text(
                    "not an archive",
                    encoding="utf-8",
                )
                return CommandResult(call, 0, "", "")
            raise AssertionError(f"unexpected command: {args}")

    with pytest.raises(SyncWorkflowError) as exc_info:
        run_sync(validate_config(VALID_CONFIG), repo_root=tmp_path, runner=BadArchiveRunner(tmp_path))

    assert "unpack failed" in str(exc_info.value)


def _write_chart_archive(archive_path: Path, tmp_path: Path, chart_dir_name: str) -> None:
    chart_source = tmp_path / f"chart-source-{chart_dir_name}"
    chart_root = chart_source / chart_dir_name
    chart_root.mkdir(parents=True, exist_ok=True)
    (chart_root / "Chart.yaml").write_text(
        f"name: {chart_dir_name}\nversion: 1.0.0\n",
        encoding="utf-8",
    )
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(chart_root, arcname=chart_dir_name)
