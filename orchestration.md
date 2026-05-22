# Agent Workflow

## Principle

The user acts as a task setter, not as a line-by-line coder.

The system works through an orchestrator that turns a product goal into small tasks, assigns each task to a specialized agent, requires tests, and only reports back when there is a useful decision or a verified result.

## Agents

### Orchestrator

Owns the whole run.

Inputs:

- product brief
- current task
- repository state
- previous run reports

Responsibilities:

- split work into small tasks
- assign each task to one specialized agent
- define acceptance criteria
- decide when a task is blocked
- require tests before completion
- produce the final report

Output:

- task plan
- agent assignments
- final status report

### Product Planner

Turns a vague feature into a small implementation task.

Responsibilities:

- clarify the behavior
- define inputs and outputs
- define out-of-scope items
- identify risks and assumptions
- write acceptance criteria

Output:

- task markdown
- acceptance criteria
- test strategy

### Implementer

Writes the smallest useful implementation.

Responsibilities:

- follow existing repository structure
- keep changes scoped to the task
- add or update tests
- avoid unrelated refactors

Output:

- code changes
- implementation notes

### Reviewer

Reviews the changes as a skeptical engineer.

Responsibilities:

- look for bugs, regressions, missing tests, and unclear behavior
- verify that acceptance criteria are covered
- avoid style-only commentary unless it affects maintainability

Output:

- findings ordered by severity
- required fixes
- residual risks

### Tester

Owns verification.

Responsibilities:

- run unit tests
- run regression tests
- run e2e tests when available
- capture commands and results
- explain failures clearly

Output:

- test report
- failed command details
- recommended next action

## Communication Contract

Each agent must return:

- what it changed or discovered
- which files it touched
- which assumptions it made
- which tests it ran
- what remains risky or blocked

Agents must not silently skip tests. If a test cannot run, the agent must say why.

## Test Layers

### Unit Tests

Fast tests for pure logic.

For Helm Patch Syncer, examples:

- YAML config parsing
- required-field validation
- image reference normalization
- local registry target mapping
- rendered manifest image extraction

### Regression Tests

Fixture-based tests that lock expected behavior.

For Helm Patch Syncer, examples:

- sample config produces expected `plan` output
- sample rendered Kyverno manifest produces expected image list
- image rewrite mapping remains stable
- invalid configs fail with stable error messages

### E2E Tests

Full workflow tests with real external tools.

For Helm Patch Syncer, the target e2e test is:

- start local OCI registry
- start or reuse local `k3s`
- download a pinned Kyverno chart version
- render original chart
- find upstream images
- mirror images with `skopeo`
- apply patch
- rewrite images to local registry
- push patched chart
- install chart from local registry
- verify pods use local image refs

## First Implementation Slice

Build only:

```bash
chartpatch plan config.yaml
```

This command does not download charts, call Helm, use Docker, use `skopeo`, or modify remote state.

It only:

- reads YAML
- validates required fields
- prints the planned source chart
- prints the patch file
- prints the local registry
- prints verification steps

## Why This Slice Comes First

This slice establishes the product's contract with the user.

If the config and plan are unstable, later agents will waste effort debugging Helm, Docker, or Kubernetes while the real problem is unclear input.

Once this slice is tested, later agents can add one workflow step at a time:

1. `helm pull`
2. unpack chart
3. `helm template`
4. image detection
5. `skopeo` mirroring
6. patch application
7. image rewriting
8. chart packaging and push
9. local `k3s` e2e
