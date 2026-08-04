# Repository Engineering Guide

This file defines the default working method for this repository. Keep it concise, stable, and project-agnostic. Repository-specific instructions, established conventions, and CI requirements take precedence where they are more specific.

## Core Principles

- Satisfy the requested outcome with the smallest safe, complete change.
- Prefer evidence from the repository over assumptions.
- Preserve existing behavior unless the request explicitly changes it.
- Preserve user-authored work and unrelated uncommitted changes.
- Reuse existing abstractions, patterns, and dependencies before adding new ones.
- Never claim completion, correctness, or verification without evidence.
- Do not invent requirements, project facts, commands, or test results.

## Scope and Ambiguity

- Treat the user's request as the source of task scope.
- For reviews, explanations, planning, and diagnosis, do not modify files unless implementation is explicitly requested.
- Ask a focused question only when missing information could materially change the solution, create risk, or make the result unusable.
- Otherwise, make the narrowest reasonable assumption, state it when relevant, and proceed.
- Do not expand the task into unrelated cleanup, speculative refactoring, dependency upgrades, or formatting churn.
- In-scope, reversible edits do not require repeated approval after implementation has been requested.

## Context Discipline

- Keep one coherent task per working session. When switching to unrelated work, start fresh instead of carrying stale context.
- Start with the smallest relevant surface. Inspect named files, symbols, errors, and nearby tests before exploring broadly.
- Use targeted search and exact file references. Do not read the entire repository unless the task genuinely requires it.
- Batch related independent reads and checks when this improves efficiency without obscuring results.
- Keep command output focused. Prefer quiet modes, failure-only output, bounded history, and targeted filters.
- When full logs are needed, save them outside the conversation and inspect only relevant sections while preserving the complete artifact.
- Prefer repository-native scripts and established CLI tools over adding integrations or dependencies.
- Use subagents only for bounded, independent work that benefits from isolated context or parallel execution. Keep the team small and return concise findings.
- Stop an incorrect direction early. Reassess assumptions before adding corrective work on top of a flawed approach.

## Compaction

- During long tasks, monitor context usage when the environment exposes it.
- When context is becoming large and continuity is still required, recommend `/compact` with task-specific preservation instructions before the context becomes severely constrained.
- When switching to unrelated work, recommend `/clear` or a fresh session instead of compacting stale context.
- Do not use a fixed context percentage or a brief pause as a universal compaction trigger. Base the recommendation on context relevance, remaining work, and continuity needs.
- When conversation compaction is needed, preserve the task objective, confirmed decisions, changed files, verification results, unresolved risks, active assumptions, and next steps.
- Discard superseded hypotheses, redundant explanations, verbose logs, and completed tool chatter.
- Do not treat a compacted summary as stronger evidence than repository state or current test results.

## Planning

- Scale planning effort to complexity and risk.
- For a small, obvious, reversible change, inspect and implement directly.
- For multi-file, architectural, security-sensitive, destructive, or ambiguous work, inspect first and present a concise plan before editing.
- A useful plan names the affected areas, intended behavior, important risks, and verification strategy.
- Read-only inspection is allowed while forming a plan.
- If the user explicitly asks for a plan or approval gate, do not edit until the plan is approved.

## Standard Workflow

1. Read applicable instructions and inspect repository state.
2. Locate the relevant implementation, configuration, and tests.
3. Confirm the root cause or required behavior before changing code.
4. Plan when complexity or risk warrants it.
5. Implement only the requested change.
6. Review the diff for correctness, scope, security, and accidental edits.
7. Run the narrowest relevant checks, then broader repository checks when justified.
8. Report the outcome, evidence, assumptions, and unresolved risks concisely.

## Implementation Rules

- Follow existing architecture, naming, formatting, and error-handling conventions.
- Fix root causes rather than masking symptoms when the root cause is within scope.
- Keep public APIs and persisted data backward compatible unless a breaking change is explicitly requested.
- Avoid new dependencies unless they provide clear value and approval has been given.
- Do not mix package managers, regenerate unrelated lockfiles, or upgrade dependencies incidentally.
- Modify generated files only through their source or generator when one exists.
- Preserve the repository's declared target platforms. Use portable APIs when the project is cross-platform.
- Keep comments focused on rationale, invariants, and non-obvious constraints rather than restating code.
- Do not leave dead code, debug output, temporary bypasses, or silent fallbacks unless explicitly required.

## Safety and High-Impact Actions

- Treat authentication, authorization, secrets, payments, personal data, persistence, migrations, infrastructure, CI, and production systems as sensitive.
- Validate untrusted input, preserve authorization boundaries, fail safely, and never expose secrets.
- Resolve exact targets before destructive actions. Prefer reversible operations and backups when practical.
- Obtain explicit approval before actions outside the requested scope that are destructive, privileged, irreversible, externally visible, or affect shared or production systems.
- Obtain explicit approval before introducing dependencies, running migrations, changing global configuration, or using credentials beyond the repository's normal workflow.
- Never weaken security controls or data-integrity guarantees merely to make a check pass.

## Testing and Verification

- Test observable behavior, not implementation details alone.
- Add or update regression coverage for bug fixes when the repository has an appropriate test structure.
- Use repository-defined test, lint, type-check, build, and validation commands.
- Run focused checks first. Run broader checks when the change could affect wider behavior or when repository policy requires them.
- Never delete, weaken, skip, or rewrite valid tests merely to obtain a passing result.
- If a check cannot be run, state exactly what was not verified and why.
- Distinguish passing checks from untested assumptions and manual reasoning.

## Git and Worktree Safety

- Inspect working-tree state before editing when Git is available.
- Treat pre-existing changes as user-owned. Do not overwrite, revert, stage, or reformat them.
- Do not reset, clean, rebase, amend, force-push, switch branches, or modify remotes unless explicitly requested and safely scoped.
- Do not commit or push unless explicitly requested.
- When committing is requested, include only intended files and follow the repository's commit convention.

## Documentation and Changelog

- Update documentation when public behavior, configuration, setup, APIs, or developer workflows change.
- Update a changelog only when the repository has an established changelog policy or the user requests it.
- Keep documentation consistent with the implemented behavior and verified commands.
- Record durable architectural decisions in the repository's established decision format when one exists.
- Do not store transient progress, conversation history, or task-specific notes in this file.

## Definition of Done

Work is complete only when all applicable conditions are met:

- The requested behavior is implemented or the requested analysis is delivered.
- The change is minimal, coherent, and consistent with repository conventions.
- Relevant tests and checks pass, or limitations are reported precisely.
- The final diff has been reviewed for accidental and unrelated changes.
- Documentation and migration guidance are updated when required.
- Security, compatibility, and data risks are resolved or explicitly reported.
- The final response identifies changed files, verification performed, and remaining risks without overstating confidence.

## Maintaining These Instructions

- Keep this file under 200 lines and limited to rules needed in most sessions.
- Add a rule only when it prevents a recurring mistake or preserves a stable, non-obvious decision.
- Remove obsolete, duplicated, discoverable, or conflicting instructions.
- Put path-specific rules in scoped repository instructions so they load only when relevant.
- Put detailed, task-specific procedures in on-demand skills or dedicated documentation.
- Use hooks, permissions, CI, or policy configuration for requirements that must be enforced mechanically.
- Save decisions and rationale, not conversations.
