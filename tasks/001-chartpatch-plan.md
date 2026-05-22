# Task 001: `chartpatch plan`

## Goal

Implement the first CLI command:

```bash
chartpatch plan config.yaml
```

The command validates a YAML config and prints a deterministic execution plan for one Helm chart.

## User Story

As a task setter, I want to describe one chart sync job in YAML and ask the tool what it will do, so that I can verify the job before any chart download, image copy, patching, or registry push happens.

## Input

Example:

```yaml
registry:
  url: localhost:5000

chart:
  name: kyverno
  source:
    repo: https://kyverno.github.io/kyverno/
    chart: kyverno
    version: 3.3.7
  patch:
    file: patches/kyverno.patch
  output:
    chart_ref: oci://localhost:5000/helm/kyverno
  verification:
    helm_lint: true
    helm_template: true
```

## Expected Output

The exact format may be refined by the implementer, but it must be deterministic and easy to snapshot-test.

It should include:

- source repository
- source chart name
- source chart version
- patch file
- local registry URL
- output chart reference
- enabled verification steps

## Validation

The command must fail with a non-zero exit code if required fields are missing:

- `registry.url`
- `chart.name`
- `chart.source.repo`
- `chart.source.chart`
- `chart.source.version`
- `chart.patch.file`
- `chart.output.chart_ref`

## Unit Tests

Required:

- valid config parses successfully
- missing `registry.url` fails
- missing chart source version fails
- verification defaults are handled predictably

## Regression Tests

Required:

- sample Kyverno config produces stable plan output
- invalid config produces stable error output

## E2E Tests

Not required for this task.

The e2e test begins after the tool can download and render a chart.

## Out Of Scope

- calling `helm`
- calling `skopeo`
- starting Docker registry
- starting `k3s`
- applying patches
- rewriting image references
- pushing OCI artifacts

## Agent Assignments

Planner:

- confirm config shape and expected output
- keep scope limited to `plan`

Implementer:

- create the CLI structure
- implement config parsing and validation
- implement deterministic plan output
- add unit tests

Reviewer:

- verify that invalid configs fail clearly
- check that no Helm/Docker behavior leaked into this slice
- check that the output can be regression-tested

Tester:

- run unit and regression tests
- report exact commands and results
