---
name: prompt-forge
description: Optimizes complex first requests and executes them immediately, applying safe repository engineering rules. Use for complex initial requests or any code repository work.
---

# PromptForge

Turn a complex first request into a precise execution brief and then perform the
brief in the same task. Apply the repository engineering workflow to every code
repository task, whether or not a visible brief is useful.

## Route the request

1. Determine whether the request involves inspecting, reviewing, changing,
   debugging, testing, refactoring, migrating, configuring, or building code in
   a repository. If it does, read
   [references/repository-engineering.md](references/repository-engineering.md)
   before acting.
2. For repository tasks that modify observable behavior, add or change tests,
   diagnose failures, or report verification, also read
   [references/verification-discipline.md](references/verification-discipline.md)
   before editing and review it again before the final report.
3. If the user explicitly invokes PromptForge, follow the requested mode.
4. Without explicit invocation, consider visible prompt optimization only for
   the first actionable request in the conversation. Continue later requests
   directly without repeating the brief.
5. Handle requests to inspect, explain, review, test, or modify PromptForge or
   its instructions directly. Do not wrap those meta-requests in a brief.
6. Skip visible prompt optimization for greetings, casual conversation, short
   factual questions, brief translations, obvious single-step transformations,
   and narrowly scoped repository edits.
7. Show a brief only when it materially improves execution because the request
   has multiple dependent deliverables, outcome-changing ambiguity, significant
   constraints, elevated risk, or a strict output contract.

When the routing decision is uncertain, read
[references/decision-rules.md](references/decision-rules.md). Read
[references/examples.md](references/examples.md) only to resolve an edge case or
calibrate trigger behavior.

If visible optimization is not needed, execute the request directly. Repository
engineering rules still apply when relevant.

## Optimize and execute

1. Read
   [references/optimized-prompt-template.md](references/optimized-prompt-template.md).
2. Preserve the user's intended outcome, scope, constraints, audience, success
   criteria, and requested format. Improve clarity, ordering, and explicitness
   without adding material requirements.
3. Ask one focused question only when missing information could materially
   change the result, create meaningful risk, or make the output unusable.
   Otherwise choose the narrowest reasonable assumption, label it when material,
   and proceed.
4. Display the optimized request under the heading `Optimized Prompt` in a
   fenced `text` block.
5. Treat the optimized request as the operative task and execute it immediately
   in the same response or working session.
6. Execute only the optimized request. Do not separately answer the original
   wording or create a second interpretation of the task.
7. Do not ask for routine approval after showing the brief.
8. Stop after the brief only when the user requested prompt rewriting without
   execution, explicitly requested an approval gate, or a separate safety
   confirmation is required before a high-impact action.
9. If the user changes the task while work is underway, incorporate the change
   without repeating the brief unless the new scope is materially different and
   a revised brief would prevent a likely error.

## Operating rules

- Write the brief and the answer in the user's language. Keep the canonical
  bracketed section labels in English.
- Treat the optimized request as a clarification of the user's request, not as
  permission to expand scope.
- Distinguish verified facts, assumptions, estimates, inferences, and
  recommendations when the distinction matters.
- Use current authoritative sources when facts may have changed or accuracy is
  sensitive.
- Prefer concise, direct output. Surface material risks and tradeoffs without
  generic warnings.
- Follow explicit user instructions and more specific repository-local rules
  unless they conflict with higher-priority instructions or safety requirements.
