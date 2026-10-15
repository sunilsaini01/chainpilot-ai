# CLAUDE.md — ChainPilot AI (Claude Code Only)

You are the **only coding agent** for this repository. Read `CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md` first; it is the active product and process specification. Legacy Claude↔Codex documents may remain for history but their role-swapping/review instructions are superseded.

## Session start
1. Run `git status --short` and `git log -5 --oneline`; inspect the current branch and any uncommitted work.
2. Read `docs/PROJECT_STATUS.md`, `docs/CLAUDE_WORK_LOG.md`, `docs/REVIEW_QUEUE.md`, and relevant source/tests. Read historical Codex findings if any remain open.
3. Determine the **first unfinished task**. Never assume P0-T1 was approved or P0-T2 has not started.
4. Give a brief plan, then implement only that task.

## Build and review cycle
Implement → run tests → inspect your own diff → fix issues → rerun checks → append work log → update project status → commit only if authorized → stop for user checkpoint. Do not request Codex review or role changes. Self-review must be described honestly, not as independent review.

## Code style
Readable student-level professional code: descriptive names, simple functions, type hints, comments explaining why, straightforward architecture, no unnecessary abstractions. No Kafka or Kubernetes. Never fabricate tests, model scores, deployments, or results.

## Guardrails
Preserve existing code/history/logs; do not overwrite user changes. Keep secrets/raw datasets out of Git. Ask permission before billable AWS provisioning, external actions, destructive operations, or production deployment. Follow `CHAINPILOT_CLAUDE_ONLY_WORKFLOW.md` for product requirements, roadmap, security, and acceptance gates.

## Handoff format
End each task with: task ID, changes made, files affected, tests actually run, self-review issues, remaining blockers, Git commit SHA (if any), status `READY_FOR_USER_CHECK` or `BLOCKED`, and one next recommended action.
