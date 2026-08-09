# Verification and Behavioral Change Discipline

Apply this guide to repository tasks that modify observable behavior, add or
change tests, diagnose failures, or report verification. Read it before editing
and review it again before the final report.

## Observable behavior

Treat a change as behavioral when it changes any externally observable contract,
including return values, thrown errors, rejected promises, observable next,
error, or complete signals, retries, timing, state transitions, side effects,
or fallback behavior.

Describe the relevant contract before and after the change.

Do not describe a change as non-behavioral, diagnostic-only, or compatibility
preserving merely because the success path is unchanged.

When compatibility cannot be proven, state the affected contract and residual
risk explicitly.

## Impact claims

Separate direct evidence from inferred impact.

Repository-wide search counts show prevalence, not necessarily end-to-end
runtime behavior.

Do not claim that every caller is affected unless all relevant control-flow
paths were traced or executable evidence demonstrates repository-wide impact.

Use qualified wording such as `may affect`, `can affect`, or `appears to affect`
when the impact is inferred.

Support broad impact claims with representative traced call paths,
configuration, or executable tests.

## Test executability

Before adding a regression test, identify all of the following.

1. The test runner.
2. The test configuration.
3. The command that executes the test.
4. The configuration or file pattern that includes the new test.

A test result is verified only when an executed command included and ran that
test.

A test file may be syntax checked or type checked without executing its
behavior. Report that narrower coverage explicitly.

A production type-check does not verify test files unless the selected
configuration includes those files.

If no runnable test path exists, report that limitation before claiming
regression coverage.

Do not say that an unexecuted test passes, should pass, or would pass.

Add an unexecuted test only when the user requested regression coverage or the
repository has an established test structure that makes the intended placement
clear. Label the test as unexecuted and unverified.

## Final claim audit

Before the final response, classify every material claim as one of the following.

1. Verified by an executed command.
2. Supported by repository evidence.
3. An inference based on stated evidence.
4. Unverified.

For every executed command, state what it actually covered.

Do not infer that a file was compiled, linted, tested, or packaged merely because
a related command passed.

Avoid unsupported certainty words such as `safe`, `guaranteed`, `complete`,
`no behavior change`, and `will pass`.

Report changed contracts, verification boundaries, residual risks, and any
unexecuted checks.
