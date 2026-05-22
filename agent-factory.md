# Agent Factory Specification

## Goal

Build a local agent factory that can take a product brief, split it into small software tasks, assign those tasks to specialized agents, require tests and review, and produce working code with an auditable run history.

The first product brief for this factory is `feature.md`, which describes Helm Patch Syncer.

The factory itself is the primary system. Helm Patch Syncer is only the first workload.

## Core Idea

In the first version, agents are Python worker processes.

An agent is:

- a Python worker entrypoint
- a role definition
- a prompt
- a set of allowed tools
- an input artifact contract
- an output artifact contract

The factory runtime is also Python:

- creates runs
- reads config
- creates task queues
- starts agent workers
- assigns jobs to workers
- passes artifact paths between workers
- enforces gates
- records decisions and reports
- resumes failed or paused runs

This makes the factory concurrent without turning each agent into a hand-written AI system.

The Python worker owns process behavior. The LLM backend still owns reasoning and code generation.

## Launch Model

The user starts one factory run:

```bash
agent-factory run feature.md
```

Optional:

```bash
agent-factory run feature.md --config factory.yaml
agent-factory resume runs/001
agent-factory stop runs/001
agent-factory status runs/001
```

The runtime starts one orchestrator process and a configurable worker pool:

```text
orchestrator
  -> planner worker pool
  -> architect worker pool
  -> implementer worker pool
  -> reviewer worker pool
  -> tester worker pool
```

For the first real concurrent version, the factory should run:

```text
1 planner
1 architect
1 task generator
2 implementers
1 reviewer
1 tester
```

The exact worker count lives in `factory.yaml`.

The factory creates a run directory:

```text
runs/
  001/
    input/
      feature.md
      factory.yaml
    state.json
    plan.md
    tasks/
      001-chartpatch-plan.md
      002-cli-skeleton.md
    agents/
      planner.report.md
      architect.report.md
      implementer.report.md
      reviewer.report.md
      tester.report.md
    logs/
      commands.log
      events.jsonl
    decisions.md
    final-report.md
```

The run directory is the shared memory between agents.

Agents do not need to chat directly. They communicate by writing structured artifacts into the run directory and by moving jobs through queues.

## Concurrency Model

The factory uses job queues, not ad hoc threads.

Each job has:

- id
- role
- task file
- input artifacts
- expected output artifacts
- dependencies
- status
- lease owner
- attempt count

Example:

```json
{
  "id": "job-007",
  "role": "implementer",
  "task": "tasks/003-image-detection.md",
  "depends_on": ["job-004"],
  "status": "queued",
  "lease_owner": null,
  "attempt": 0
}
```

Workers pull jobs that match their role.

When an implementer finishes one task, it immediately asks the queue for the next implementer job. This is the core factory behavior.

The orchestrator does not wait idly for the entire run to finish. It continuously:

- watches job state
- unlocks dependent jobs
- sends failed jobs back for fixes
- pauses on gates that need user approval
- writes events to `events.jsonl`

## What Can Run In Parallel

Parallel:

- independent implementation tasks
- independent research tasks
- review of task A while implementation of task B continues
- unit/regression test jobs for completed tasks
- documentation/report generation

Sequential or gated:

- initial product planning before task generation
- architecture decision before broad implementation
- two implementers editing the same files
- final release/e2e gate
- destructive commands

The factory must avoid parallel writes to the same ownership area.

Each task should declare a write scope:

```yaml
write_scope:
  - src/chartpatch/config.py
  - tests/test_config.py
```

The orchestrator must not assign two active jobs with overlapping write scopes.

## User Role

The user is not expected to micromanage implementation.

The user does:

- starts a run
- sets constraints and priorities
- approves major scope changes
- answers blockers when the factory cannot infer the answer
- stops or resumes runs
- reviews final reports

The user does not:

- assign every subtask by hand
- read every line of generated code
- manually run every test
- manually coordinate agent context

The factory should ask the user only when:

- the product goal is ambiguous
- a destructive action is required
- credentials or paid external services are needed
- tests reveal a product-level decision
- scope must change

## Runtime State Machine

A factory run has a global state:

```text
created
  -> planning
  -> architecture
  -> task_generation
  -> executing
  -> completed
```

Failure states:

```text
blocked
failed
stopped
```

The orchestrator owns the state machine.

Individual jobs have their own state:

```text
queued
  -> leased
  -> running
  -> produced_artifacts
  -> review_queued
  -> test_queued
  -> passed
```

Failure job states:

```text
needs_fix
blocked
failed
cancelled
```

## Orchestrator

The orchestrator is a Python process.

Responsibilities:

- load `feature.md`
- load `factory.yaml`
- create a run directory
- create and persist job queues
- start configured worker processes
- assign jobs by role and write scope
- validate that each worker produced required outputs
- decide whether to continue, retry, pause, or stop
- enforce test gates
- enforce write-scope locking
- record all job transitions
- write `final-report.md`

The orchestrator should be deterministic where possible.

It should not hide agent outputs. Every important decision must be written to the run directory.

## Python Agent Worker

Each agent worker is a Python process started by the orchestrator.

Example:

```bash
python -m agent_factory.worker --role implementer --run runs/001
```

The worker loop:

```text
load run state
claim next queued job for role
load task and input artifacts
render role prompt
call backend
write required artifacts
mark job produced_artifacts or blocked
repeat
```

Workers should be stateless between jobs except for:

- role config
- backend config
- local process logs

Durable state lives in the run directory.

This lets a worker crash without losing the whole run.

## Agent Backend

The first version can support one backend:

```text
codex exec
```

The Python worker calls its backend by running something like:

```bash
codex exec --cd /path/to/repo "$(cat prompts/planner.md)"
```

Later backends may include:

- OpenAI Agents SDK
- LangGraph
- Claude Code SDK
- local model runners

The factory config should hide the backend choice from task definitions.

## Agent Definitions

Agent definitions live in:

```text
agents/
  planner.md
  architect.md
  implementer.md
  reviewer.md
  tester.md
```

Each agent definition contains:

- role
- responsibilities
- allowed inputs
- required outputs
- constraints
- refusal/blocker rules

## Required Agents

### Planner

Purpose:

Turn the product brief into a small, ordered task plan.

Inputs:

- `feature.md`
- previous decisions if any

Outputs:

- `plan.md`
- first task candidates
- open questions

### Architect

Purpose:

Choose the technical shape of the system before implementation begins.

Inputs:

- `feature.md`
- `plan.md`

Outputs:

- architecture decision record
- module boundaries
- test strategy
- risk list

### Task Generator

Purpose:

Convert the plan into small implementation tasks.

Inputs:

- `plan.md`
- architecture decision record

Outputs:

- `tasks/*.md`

### Implementer

Purpose:

Implement one task at a time.

Inputs:

- one task file
- relevant prior reports
- repository state

Outputs:

- code changes
- implementation report
- tests added or updated

### Reviewer

Purpose:

Find bugs, regressions, missing tests, unclear behavior, and scope drift.

Inputs:

- task file
- diff
- implementation report

Outputs:

- review report
- severity-ordered findings
- pass/fail decision

### Tester

Purpose:

Run verification and produce a test report.

Inputs:

- task file
- repository state
- reviewer requirements

Outputs:

- commands run
- results
- failures
- pass/fail decision

## Gates

The orchestrator must enforce gates.

### Planning Gate

The run cannot continue unless:

- the goal is restated clearly
- out-of-scope items are listed
- the first task is small enough
- open questions are either answered or explicitly deferred

### Architecture Gate

The run cannot continue unless:

- the initial stack is chosen
- module boundaries are clear
- test strategy exists
- risky external tools are identified

### Review Gate

The run cannot continue unless:

- reviewer has passed the task
- or all blocking findings are assigned back to implementer

### Test Gate

The run cannot complete unless:

- required unit tests pass
- required regression tests pass
- e2e tests are either passing or explicitly not required for this task

### Stuck Gate

The orchestrator must stop and require human intervention when the run is probably wasting time or tokens.

Initial stuck criteria:

- a worker exceeds its configured `timeout_seconds`
- a backend exits with a non-zero code
- a worker does not produce required output artifacts
- a job dependency never becomes `passed`
- a future fix loop exceeds `max_fix_loops`

When the stuck gate triggers, the orchestrator must:

- mark the run `blocked` or `failed`
- write the role and reason into `state.json`
- write a `human_intervention_required` event
- preserve stdout/stderr logs
- avoid retrying indefinitely
- tell the user which artifact or log to inspect

Long-running agent frameworks can later make this policy richer, but the runtime must own these base safety checks.

## Progress Logging

The factory should make progress visible while it runs.

The orchestrator writes progress to:

- stdout for the human operator
- `runs/<id>/logs/events.jsonl` for durable audit

Examples:

```text
[agent-factory] created run 004
[agent-factory] starting planner worker with timeout 180s
[agent-factory] planner worker finished
[agent-factory] paused at planning_gate
```

The user can inspect a run:

```bash
agent-factory status runs/004
```

## Factory Config

Example `factory.yaml`:

```yaml
factory:
  name: local-agent-factory
  run_root: runs
  runtime: python_workers
  require_review: true
  require_tests: true
  max_fix_loops: 3

runtime:
  python_workers:
    queue_file: queue.json
    event_log: logs/events.jsonl
    lock_file: locks.json
    poll_interval_seconds: 2

backend:
  codex_exec:
    command: codex
    args:
      - exec
      - --cd
      - "{repo}"

agents:
  planner:
    worker_module: agent_factory.worker
    prompt: agents/planner.md
    concurrency: 1
    outputs:
      - plan.md
  architect:
    worker_module: agent_factory.worker
    prompt: agents/architect.md
    concurrency: 1
    outputs:
      - architecture.md
  task_generator:
    worker_module: agent_factory.worker
    prompt: agents/task-generator.md
    concurrency: 1
    outputs:
      - tasks/
  implementer:
    worker_module: agent_factory.worker
    prompt: agents/implementer.md
    concurrency: 2
    outputs:
      - implementation-report.md
  reviewer:
    worker_module: agent_factory.worker
    prompt: agents/reviewer.md
    concurrency: 1
    outputs:
      - review-report.md
  tester:
    worker_module: agent_factory.worker
    prompt: agents/tester.md
    concurrency: 1
    outputs:
      - test-report.md
```

## First Factory Milestone

Do not build Helm Patch Syncer yet.

Build enough factory machinery to create a run and a queue:

```bash
agent-factory run feature.md --dry-run
```

It should:

- create `runs/001`
- copy `feature.md` into `runs/001/input/`
- create `state.json`
- create `queue.json`
- create `locks.json`
- create a planned worker topology
- render agent prompts with artifact paths
- stop before starting workers or calling any LLM backend

## Second Factory Milestone

Run only the Planner worker:

```bash
agent-factory run feature.md --only planner
```

It should:

- start one planner worker process
- create a planner job
- let the planner worker claim the job
- call the planner backend from the worker
- produce `runs/001/plan.md`
- record the backend command
- stop at the planning gate

## Third Factory Milestone

Run the first sequential loop through workers:

```text
Planner -> Architect -> Task Generator -> Implementer -> Reviewer -> Tester
```

Only for the first generated task.

The run is successful if:

- the first task is implemented
- review passes
- unit and regression tests pass
- final report explains what changed

## Fourth Factory Milestone

Run parallel implementation:

```text
Planner -> Architect -> Task Generator
                         -> Implementer 1 -> Reviewer -> Tester
                         -> Implementer 2 -> Reviewer -> Tester
```

The run is successful if:

- two independent implementation tasks can run at the same time
- write-scope locks prevent conflicting edits
- reviewer and tester jobs are generated per completed implementation job
- failed review/test jobs create fix jobs
- implementer workers continue to the next available job

## Why Workers Come First

The factory needs concurrency, but concurrency must be controlled.

The first useful unit is not a hand-written Python agent with custom logic. It is a generic Python worker that can run any role:

```bash
python -m agent_factory.worker --role implementer --run runs/001
python -m agent_factory.worker --role reviewer --run runs/001
```

Role-specific behavior comes from:

- prompt file
- input artifacts
- output contract
- allowed tools
- gate rules

This gives the factory real parallel execution while keeping agent behavior configurable.

## Framework Role

LangGraph, LangChain, and workflow frameworks do not replace the worker runtime.

They can help with:

- graph-shaped orchestration policy
- conditional routing
- retry loops
- human-in-the-loop checkpoints
- resumable execution
- tracing and observability

They should not be the only safety mechanism.

The local factory still needs explicit runtime controls:

- process timeouts
- required output checks
- queue state
- write-scope locks
- stdout/stderr logs
- Git gate commits

Recommended evolution:

1. Keep Python workers as the execution layer.
2. Add LangGraph inside the orchestrator when the state machine becomes too complex to keep as simple Python functions.
3. Use Superpowers-style workflow rules as prompts and gates.
4. Add LangChain only if the factory needs model/tool adapters, retrieval, or complex chains.
