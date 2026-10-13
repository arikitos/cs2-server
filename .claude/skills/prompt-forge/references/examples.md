# Trigger Examples

Use these examples to calibrate routing. Do not copy them mechanically.

| Request                                                                                                               | Decision                                        | Reason                                                       |
| --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- | ------------------------------------------------------------ |
| "What is dependency injection?"                                                                                       | Direct answer                                   | Clear factual question                                       |
| "Translate this sentence to Hebrew."                                                                                  | Direct answer                                   | Obvious single-step transformation                           |
| "Rename `timeoutMs` in this repository."                                                                              | Direct repository execution                     | Narrow edit; framing adds no value                           |
| "Explain why PromptForge triggered."                                                                                  | Direct answer                                   | Meta-request about the skill                                 |
| "Review this service, rank its security and concurrency risks, refactor it, add tests, and give me a migration plan." | Show brief, then execute under repository rules | Multiple dependent deliverables and material repository risk |
| "Compare current enterprise coding assistants using primary sources and recommend one for a regulated company."       | Show brief, then execute                        | Current research, decision criteria, and high accuracy risk  |
| A later follow-up that adds one constraint                                                                            | Direct continuation                             | Not the first actionable request                             |
| An explicitly requested rewrite only                                                                                  | Show brief and stop                             | The user requested prompt editing only                       |
| "Give me a plan first and wait for approval."                                                                         | Show the requested plan and wait                | The user explicitly requested an approval gate               |

## Detailed positive example

Request:

> Review this TypeScript service, identify concurrency and security risks,
> propose a refactor, add tests, and explain the migration plan.

Expected brief:

```text
[Task]
Review the provided TypeScript service, identify and rank concurrency and
security risks, implement an appropriate refactor, add focused tests, and
explain a safe migration plan.

[Context]
Preserve behavior and public interfaces unless a breaking change is explicitly
requested. Base findings on repository evidence and label material uncertainty.

[Persona]
Senior TypeScript engineer with application security experience.

[Format]
Provide risk findings, changed files, tests and results, migration steps, and
unresolved risks. Reference exact files or symbols.

[Tone]
Direct, calm, precise, and constructively critical.
```

After displaying the brief, execute the task immediately under the repository
engineering workflow. Do not ask for routine approval.

This example does not assume that the service is in production or invent facts
about its deployment environment.
