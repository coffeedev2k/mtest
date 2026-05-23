from __future__ import annotations

from pathlib import Path
import tarfile

import pytest

import chartpatch.workflow as workflow
from chartpatch.config import validate_config
from chartpatch.images import ImageTargetMapping
from chartpatch.rewrite import ImageRewriteError
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
        git_am_result: CommandResult | None = None,
        create_archive: bool = True,
        extra_archive: bool = False,
        archive_chart_dir: str = "kube-prometheus-stack",
    ) -> None:
        self.tmp_path = tmp_path
        self.pull_result = pull_result
        self.template_result = template_result
        self.skopeo_results = list(skopeo_results)
        self.git_am_result = git_am_result
        self.create_archive = create_archive
        self.extra_archive = extra_archive
        self.archive_chart_dir = archive_chart_dir
        self.calls: list[tuple[str, ...]] = []
        self.cwd_by_call: list[Path | None] = []
        self.template_call_count = 0

    def run(self, args: list[str], *, cwd: Path | None = None) -> CommandResult:
        call = tuple(args)
        self.calls.append(call)
        self.cwd_by_call.append(cwd)
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
            self.template_call_count += 1
            if self.template_call_count == 1:
                return self.template_result or CommandResult(
                    call,
                    0,
                    ORIGINAL_RENDER_WITH_IMAGES,
                    "",
                )
            raise AssertionError("unexpected second helm template call")
        if args[:2] == ["skopeo", "copy"]:
            if self.skopeo_results:
                return self.skopeo_results.pop(0)
            return CommandResult(call, 0, "copied\n", "")
        if args[:2] == ["git", "init"]:
            return CommandResult(call, 0, "initialized\n", "")
        if args[:2] == ["git", "config"]:
            return CommandResult(call, 0, "", "")
        if args[:2] == ["git", "add"]:
            return CommandResult(call, 0, "", "")
        if args[:2] == ["git", "commit"]:
            return CommandResult(call, 0, "[main baseline]\n", "")
        if args[:3] == ["git", "am", "--reject"]:
            if self.git_am_result is not None:
                return self.git_am_result
            return CommandResult(call, 0, "applied\n", "")
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
    assert result.applied_patch_file == tmp_path / "patches/kube-prometheus-stack.patch"
    assert result.rewrite_replacements == 2
    assert result.rewritten_files == (Path("values.yaml"),)
    assert tuple(
        (rewrite.source, rewrite.target, rewrite.replacements)
        for rewrite in result.image_rewrites
    ) == (
        (
            "docker.io/bitnami/nginx:1.27.4",
            "localhost:5000/docker.io/bitnami/nginx:1.27.4",
            1,
        ),
        (
            "registry.example.com/setup:1.0.0",
            "localhost:5000/registry.example.com/setup:1.0.0",
            1,
        ),
    )
    assert (result.unpacked_chart_path / "values.yaml").read_text(encoding="utf-8") == (
        "appImage: localhost:5000/docker.io/bitnami/nginx:1.27.4\n"
        "setupImage: localhost:5000/registry.example.com/setup:1.0.0\n"
    )
    assert [call[:2] for call in runner.calls] == [
        ("helm", "pull"),
        ("helm", "template"),
        ("skopeo", "copy"),
        ("skopeo", "copy"),
        ("git", "init"),
        ("git", "config"),
        ("git", "config"),
        ("git", "add"),
        ("git", "commit"),
        ("git", "am"),
    ]
    assert all(
        call[:2]
        not in {
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
    assert runner.calls[4:10] == [
        ("git", "init"),
        ("git", "config", "user.name", "ChartPatch"),
        ("git", "config", "user.email", "chartpatch@example.invalid"),
        ("git", "add", "--all"),
        ("git", "commit", "-m", "Baseline upstream chart"),
        ("git", "am", "--reject", str(tmp_path / "patches/kube-prometheus-stack.patch")),
    ]
    assert runner.cwd_by_call[4:10] == [result.unpacked_chart_path] * 6

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
    assert f"Applied patch: {tmp_path / 'patches/kube-prometheus-stack.patch'}" in report
    assert "Image rewrites: 2" in report
    assert (
        "  - docker.io/bitnami/nginx:1.27.4 -> "
        "localhost:5000/docker.io/bitnami/nginx:1.27.4 (1 replacements)"
    ) in report
    assert (
        "  - registry.example.com/setup:1.0.0 -> "
        "localhost:5000/registry.example.com/setup:1.0.0 (1 replacements)"
    ) in report
    assert "Image rewrite replacements: 2" in report
    assert "  - values.yaml" in report
    assert report.index("Discovered images: 2") < report.index("Image target mappings: 2")
    assert report.index("Image target mappings: 2") < report.index("Mirrored images: 2")
    assert report.index("Mirrored images: 2") < report.index("Applied patch:")
    assert report.index("Applied patch:") < report.index("Image rewrites: 2")
    assert report.index("Image rewrites: 2") < report.index("Image rewrite replacements: 2")


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
    assert not (logs_dir / "helm-template-patched.args.txt").exists()
    assert "skopeo copy docker://docker.io/bitnami/nginx:1.27.4" in (
        logs_dir / "skopeo-copy-1.args.txt"
    ).read_text(encoding="utf-8")
    assert (logs_dir / "git-am.stdout.txt").read_text(encoding="utf-8") == "applied\n"


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
    assert all(call[0] != "git" for call in runner.calls)


def test_sync_fails_when_patch_application_fails_after_mirroring(tmp_path: Path) -> None:
    runner = StubRunner(
        tmp_path,
        git_am_result=CommandResult(
            (
                "git",
                "am",
                "--reject",
                str(tmp_path / "patches/kube-prometheus-stack.patch"),
            ),
            128,
            "patch stdout\n",
            "patch stderr\n",
        ),
    )

    with pytest.raises(SyncWorkflowError) as exc_info:
        run_sync(validate_config(VALID_CONFIG), repo_root=tmp_path, runner=runner)

    message = str(exc_info.value)
    assert "patch application failed" in message
    assert "exited with code 128" in message
    assert "patch stdout" in message
    assert "patch stderr" in message
    assert [call[:2] for call in runner.calls] == [
        ("helm", "pull"),
        ("helm", "template"),
        ("skopeo", "copy"),
        ("skopeo", "copy"),
        ("git", "init"),
        ("git", "config"),
        ("git", "config"),
        ("git", "add"),
        ("git", "commit"),
        ("git", "am"),
    ]
    assert all(
        call[:2] not in {("helm", "lint"), ("helm", "package"), ("helm", "push")}
        for call in runner.calls
    )


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


def test_sync_rewrite_stage_receives_original_image_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_mappings: list[tuple[ImageTargetMapping, ...]] = []
    original_rewrite = workflow.rewrite_chart_images

    def capture_rewrite(chart_dir: Path, mappings: tuple[ImageTargetMapping, ...]):
        captured_mappings.append(mappings)
        return original_rewrite(chart_dir, mappings)

    monkeypatch.setattr(workflow, "rewrite_chart_images", capture_rewrite)

    result = run_sync(
        validate_config(VALID_CONFIG),
        repo_root=tmp_path,
        runner=StubRunner(tmp_path),
    )

    assert captured_mappings == [
        (
            ImageTargetMapping(
                source="docker.io/bitnami/nginx:1.27.4",
                target="localhost:5000/docker.io/bitnami/nginx:1.27.4",
            ),
            ImageTargetMapping(
                source="registry.example.com/setup:1.0.0",
                target="localhost:5000/registry.example.com/setup:1.0.0",
            ),
        )
    ]
    assert result.rewrite_replacements == 2


def test_sync_fails_when_rewrite_stage_fails_after_patch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = StubRunner(tmp_path)

    def fail_rewrite(chart_dir: Path, mappings: tuple[ImageTargetMapping, ...]):
        raise ImageRewriteError(
            f"image rewrite failed while writing {chart_dir / 'values.yaml'}: boom"
        )

    monkeypatch.setattr(workflow, "rewrite_chart_images", fail_rewrite)

    with pytest.raises(SyncWorkflowError) as exc_info:
        run_sync(validate_config(VALID_CONFIG), repo_root=tmp_path, runner=runner)

    message = str(exc_info.value)
    assert "image rewrite failed while writing" in message
    assert "boom" in message
    assert [call[:2] for call in runner.calls] == [
        ("helm", "pull"),
        ("helm", "template"),
        ("skopeo", "copy"),
        ("skopeo", "copy"),
        ("git", "init"),
        ("git", "config"),
        ("git", "config"),
        ("git", "add"),
        ("git", "commit"),
        ("git", "am"),
    ]
    assert all(
        call[:2] not in {("helm", "lint"), ("helm", "package"), ("helm", "push")}
        for call in runner.calls
    )


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
        def run(self, args: list[str], *, cwd: Path | None = None) -> CommandResult:
            call = tuple(args)
            self.calls.append(call)
            self.cwd_by_call.append(cwd)
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
    (chart_root / "values.yaml").write_text(
        "appImage: docker.io/bitnami/nginx:1.27.4\n"
        "setupImage: registry.example.com/setup:1.0.0\n",
        encoding="utf-8",
    )
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(chart_root, arcname=chart_dir_name)
