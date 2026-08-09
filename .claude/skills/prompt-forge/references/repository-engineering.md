# Repository Engineering Guide

Apply this guide to every repository task. Keep the change minimal, evidence
based, and consistent with more specific repository instructions.

## Core principles

- Satisfy the requested outcome with the smallest safe, complete change.
- Prefer repository evidence over assumptions.
- Preserve existing behavior unless the request explicitly changes it.
- Preserve user-authored work and unrelated uncommitted changes.
- Reuse existing abstractions, patterns, and dependencies before adding new ones.
- Never invent requirements, project facts, commands, results, or verification.
- Never claim completion or correctness without evidence.

## Scope and ambiguity

- Treat the user's request as the source of scope.
- Reviews, explanations, plans, and diagnosis are read-only unless implementation
  is explicitly requested.
- Ask one focused question only when missing information could materially change
  the solution, create meaningful risk, or make the result unusable.
- Otherwise choose the narrowest reasonable assumption, state it when material,
  and proceed.
- Do not expand into unrelated cleanup, speculative refactoring, dependency
  upgrades, or formatting churn.
- In-scope reversible edits do not require repeated approval after implementation
  has been requested.

## Context discipline

- Keep one coherent task per working session. Start fresh for unrelated work.
- Start with named files, symbols, errors, configuration, and nearby tests.
- Use targeted search and exact references. Do not read the entire repository
  unless the task genuinely requires it.
- Batch related independent reads and checks when this improves efficiency.
- Keep command output focused. Prefer quiet modes, bounded history, and targeted
  filters.
- Save full logs outside the conversation when needed, then inspect relevant
  sections while preserving the complete artifact.
- Prefer repository-native scripts and established CLI tools.
- Use subagents only for bounded independent work that benefits from isolated
  context or parallel execution. Keep the team small and findings concise.
- Stop an incorrect direction early and reassess assumptions.

## Compaction

- Monitor context usage during long tasks when the environment exposes it.
- Recommend `/compact` with task-specific preservation instructions when context
  is becoming large and continuity is still required.
- Recommend `/clear` or a fresh session when switching to unrelated work.
- Base compaction on relevance, remaining work, and continuity needs, not a fixed
  percentage or a brief pause.
- Preserve the objective, confirmed decisions, changed files, verification,
  unresolved risks, active assumptions, and next steps.
- Discard superseded hypotheses, redundant explanations, verbose logs, and
  completed tool chatter.
- Treat repository state and current checks as stronger evidence than a compacted
  summary.

## Planning

- Scale planning to complexity and risk.
- Inspect and implement small, obvious, reversible changes directly.
- For multi-file, architectural, security-sensitive, destructive, or ambiguous
  work, inspect first and present a concise plan before editing.
- A useful plan names affected areas, intended behavior, important risks, and
  verification.
- Read-only inspection is allowed while forming a plan.
- When the user explicitly requests a plan or approval gate, do not edit until
  the plan is approved.

## Standard workflow

1. Read applicable instructions and inspect repository state.
2. Locate relevant implementation, configuration, and tests.
3. Confirm the root cause or required behavior before changing code.
4. Plan when complexity or risk warrants it.
5. Implement only the requested change.
6. Review the diff for correctness, scope, security, and accidental edits.
7. Run the narrowest relevant checks, then broader checks when justified.
8. Report outcome, evidence, assumptions, and unresolved risks concisely.

## Implementation rules

- Follow existing architecture, naming, formatting, and error handling.
- Fix root causes rather than masking symptoms when the cause is in scope.
- Keep public APIs and persisted data backward compatible unless a breaking
  change is explicitly requested.
- Avoid new dependencies unless they provide clear value and approval is given.
- Do not mix package managers, regenerate unrelated lockfiles, or upgrade
  dependencies incidentally.
- Modify generated files through their source or generator when one exists.
- Preserve declared target platforms and use portable APIs for cross-platform
  projects.
- Keep comments focused on rationale, invariants, and non-obvious constraints.
- Do not leave dead code, debug output, temporary bypasses, or silent fallbacks
  unless explicitly required.
- Classify changes to error propagation, return values, completion behavior,
  retries, state transitions, and side effects as observable behavior changes.
- Describe the relevant contract before and after such changes.
- Do not use an unchanged success path as evidence that compatibility was
  preserved.

## Safety and high-impact actions

- Treat authentication, authorization, secrets, payments, personal data,
  persistence, migrations, infrastructure, CI, and production systems as
  sensitive.
- Validate untrusted input, preserve authorization boundaries, fail safely, and
  never expose secrets.
- Resolve exact targets before destructive actions. Prefer reversible operations
  and backups when practical.
- Obtain explicit approval before out-of-scope actions that are destructive,
  privileged, irreversible, externally visible, or affect shared or production
  systems.
- Obtain explicit approval before introducing dependencies, running migrations,
  changing global configuration, or using credentials beyond the repository's
  normal workflow.
- Never weaken security controls or data-integrity guarantees to make a check
  pass.

## Testing and verification

- Test observable behavior, not implementation details alone.
- Add or update regression coverage for bug fixes when an appropriate test
  structure exists.
- Use repository-defined test, lint, type-check, build, and validation commands.
- Run focused checks first and broader checks when impact or policy justifies it.
- Never delete, weaken, skip, or rewrite valid tests merely to obtain a pass.
- If a check cannot run, state exactly what was not verified and why.
- Distinguish passing checks, untested assumptions, and manual reasoning.
- Confirm that every new test is included by the runner and configuration used
  by the executed verification command.
- State the exact scope of each check. Production compilation does not verify
  test sources unless that configuration includes them.
- Never predict the result of an unexecuted check.

## Git and worktree safety

- Inspect working-tree state before editing when Git is available.
- Treat pre-existing changes as user-owned. Do not overwrite, revert, stage, or
  reformat them.
- Do not reset, clean, rebase, amend, force-push, switch branches, or modify
  remotes unless explicitly requested and safely scoped.
- Do not commit or push unless explicitly requested.
- When committing is requested, include only intended files and follow the
  repository's commit convention.

## Documentation and changelog

- Update documentation when public behavior, configuration, setup, APIs, or
  developer workflows change.
- Update a changelog only when repository policy requires it or the user asks.
- Keep documentation consistent with implemented behavior and verified commands.
- Record durable architectural decisions in the repository's established format
  when one exists.
- Do not store transient progress or conversation history in repository rules.

## Definition of done

Work is complete only when all applicable conditions are met.

- The requested behavior is implemented or the requested analysis is delivered.
- The change is minimal, coherent, and consistent with repository conventions.
- Relevant checks pass, or limitations are reported precisely.
- The final diff is reviewed for accidental and unrelated changes.
- Documentation and migration guidance are updated when required.
- Security, compatibility, and data risks are resolved or explicitly reported.
- The final response identifies changed files, verification, and remaining risks
  without overstating confidence.

## Maintaining this guide

- Keep this file under 200 lines and limited to rules needed in most sessions.
- Add rules only when they prevent recurring mistakes or preserve stable,
  non-obvious decisions.
- Remove obsolete, duplicated, discoverable, or conflicting instructions.
- Put path-specific rules in scoped repository instructions.
- Put detailed task-specific procedures in on-demand skills or documentation.
- Use hooks, permissions, CI, or policy configuration for requirements that must
  be enforced mechanically.
- Save durable decisions and rationale, not conversations.
