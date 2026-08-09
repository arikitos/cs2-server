# Decision Rules

Use this reference when it is unclear whether a visible optimized prompt will
improve the result.

## Decision order

1. **Repository route:** Apply repository engineering rules to every repository
   task, even when no visible brief is shown.
2. **Manual invocation:** Follow the user's explicit request. Produce only a
   rewrite when that is all the user requested.
3. **Conversation position:** Without manual invocation, consider visible
   optimization only for the first actionable request.
4. **Meta-request:** Handle requests about PromptForge itself directly.
5. **Clear and simple:** Continue directly when the answer or transformation is
   obvious. Repository safeguards still apply to repository work.
6. **Material benefit:** Show the brief only when explicit framing makes
   execution meaningfully clearer, safer, or more complete.

## Positive signals

- Multiple dependent subtasks, deliverables, or acceptance criteria
- Architecture, migration, strategy, research, or multi-stage implementation
- Compatibility, compliance, security, performance, or strict output constraints
- Accuracy-sensitive work requiring current or authoritative evidence
- Ambiguity that permits materially different outcomes
- Coordination across several repository areas with non-trivial regression risk

One signal is not automatically sufficient. The brief must add execution value.

## Negative signals

- Definitions, quick lookups, greetings, acknowledgements, or casual chat
- Brief translations and single-sentence rewrites
- One obvious transformation or narrowly scoped edit
- Follow-up requests after the conversation is already underway
- Cases where a brief would merely restate the request

## Execution rule

When a brief is shown, execute it immediately in the same response or working
session. Do not insert a routine approval pause.

Wait only when one of these conditions applies:

- The user requested prompt rewriting without execution.
- The user explicitly requested a plan or approval gate before changes.
- A destructive, privileged, irreversible, externally visible, shared-system,
  production, migration, dependency, credential, or similarly high-impact action
  requires explicit approval and was not already requested with an exact target.

A simple repository task proceeds directly under the repository workflow unless
one of those conditions applies.

## Ambiguity threshold

Ask a question only when critical information is missing and a reasonable
working choice could make the result incorrect, unsafe, or unusable. Otherwise
choose the narrowest reasonable default, label it when material, and proceed.

Never treat an invented fact as an assumption. An assumption is a necessary
working choice, not extra background, a new requirement, or an expansion of
scope.
