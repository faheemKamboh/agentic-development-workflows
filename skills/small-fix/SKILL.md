# Small Fix Skill

Goal: repair a narrowly scoped defect with the least risky change.

1. Inspect the file tree.
2. Read the task and the most relevant implementation/test files.
3. Identify the smallest root-cause fix; do not redesign unrelated code.
4. Replace only files that actually need changes.
5. Run the provided test command.
6. If tests fail, inspect the failure and make at most one additional focused correction.
7. Finish with a short factual summary.

Rules:
- Never weaken or delete tests to make them pass.
- Never add network calls, credentials, or unrelated dependencies.
- Preserve public behavior not mentioned in the task.
- Prefer deterministic, readable code over cleverness.
