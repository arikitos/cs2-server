# Repository Engineering Guide

These instructions apply only to this repository.

## Priority

Follow instructions in this order:

1. Explicit user request
2. Repository-local instructions and CI configuration
3. Existing codebase conventions
4. This guide

If instructions conflict or a high-impact choice is unclear, stop and ask.

## Change Scope

- Make the smallest safe change that fully satisfies the request.
- Reuse existing abstractions and conventions.
- Avoid unrelated cleanup, speculative refactors, dependency upgrades, and formatting churn.
- Preserve user-authored and pre-existing uncommitted changes.
- Never claim completion or verification without evidence.

## Workflow

Use this sequence, scaled to the task's risk:

1. Inspect relevant instructions, code, configuration, and working-tree state.
2. State a short plan for non-trivial work.
3. Implement only the requested change.
4. Review the diff for scope, correctness, security, and accidental edits.
5. Run repository-defined tests, lint, type checks, and builds relevant to the change.
6. Report results, assumptions, unresolved risks, and exact files the developer should review.

## Toolchain

- Detect the runtime and package manager from repository files.
- Use repository scripts and version-compatible features.
- Do not mix package managers, create a new lockfile, or upgrade dependencies without approval.
- Keep changes portable across Windows, macOS, and Linux. Prefer language-native path APIs and repository scripts over shell-specific behavior.

## Safety and Testing

- Test observable behavior. Add regression coverage for bug fixes when the repository supports it.
- Never weaken, delete, or skip tests merely to make checks pass.
- Treat authentication, secrets, payments, personal data, persistence, migrations, and CI/CD as sensitive.
- Validate untrusted input, fail safely, and never expose secrets.
- Report unresolved security or data-integrity uncertainty explicitly.

## Approval Required

Explain the impact and obtain explicit approval before:

- Committing, switching branches, force-pushing, or changing global configuration
- Running destructive commands such as reset, clean, or irreversible deletion
- Running migrations, privileged commands, or operations that affect shared or production systems
- Introducing or upgrading dependencies

Never commit on the user's behalf. At the end of implementation work, provide a copy-ready English Conventional Commit message using an imperative subject with no trailing period.

Never append attribution or co-authorship trailers to commit messages, including `Co-Authored-By: Claude ...`, `Generated with Claude Code`, or any similar tool or assistant credit. This applies to both suggested and executed commit messages, and to pull request descriptions.

## Changelog

After changing repository files, update `CHANGELOG.md` under `Unreleased` using the relevant heading: `Added`, `Changed`, `Fixed`, `Removed`, `Security`, or `Deprecated`.

Skip the changelog only for read-only tasks or when a more specific repository instruction explicitly excludes the change.

## Final Report

For implementation work, end with these sections:

- `Status`
- `Summary`
- `Files Changed`
- `Changelog`
- `Verification`
- `Risks / Notes`
- `Commit Message`

Keep the report concise. Include exact file paths and focused review points so the developer does not need to search for them.
