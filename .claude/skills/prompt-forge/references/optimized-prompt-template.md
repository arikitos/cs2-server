# Optimized Prompt Template

Use this exact order. Omit only the optional `[Exemplars]` section.

```text
[Task]
A clear, explicit, and actionable statement of the requested work.

[Context]
Relevant supplied background, constraints, audience, goals, success criteria,
and any necessary assumption labeled as an assumption.

[Persona]
The professional role or perspective that materially improves execution.

[Exemplars]
One to three short examples that materially clarify the requested result.

[Format]
The requested deliverables, structure, length, file types, and citation needs.

[Tone]
Direct, calm, precise, constructively critical, respectful, and nonpromotional,
unless the user requested another tone.
```

Always include `[Task]`, `[Context]`, `[Persona]`, `[Format]`, and `[Tone]`.
Include `[Exemplars]` only when examples materially improve clarity.

## Preserve intent

Identify the intended outcome, context, constraints, audience, goals, success
criteria, requested format, assumptions, and material ambiguities. Include only
items that affect the result.

You may improve wording, ordering, clarity, and the explicitness of constraints
already present or necessarily implied by the request.

Do not:

- change the goal or choose among materially different interpretations;
- invent facts, environments, audiences, deadlines, budgets, or technologies;
- add acceptance criteria that were not stated or necessarily implied;
- silently remove constraints or requested deliverables;
- expand the task to adjacent work.

When a working assumption is necessary, label it and keep it narrow. If no
assumption is required, do not manufacture one to fill `[Context]`.
