---
name: Bug report
about: Report something broken in Velure
title: "[bug] "
labels: bug
assignees: ""
---

## What happened

<!-- A clear, one-paragraph description of the bug. -->

## Reproduction

<!-- Exact steps to reproduce. Include the URLs, environment, DATA_MODE, and any API keys you used (DO NOT paste real keys). -->

1. …
2. …

## Expected

<!-- What you expected to happen. -->

## Actual

<!-- What actually happened. Include log lines, error messages, screenshots. -->

## Environment

- OS:
- Docker version:
- Commit / branch:
- `DATA_MODE`:
- Backend `GET /api/system/status` output:

```json
{
  "redis": "...",
  "postgres": "...",
  "models": "...",
  "producer": "..."
}
```

## Logs

```text
paste backend logs here
```

## Severity

- [ ] Blocker — pipeline does not run
- [ ] Major — wrong model output / dashboard broken
- [ ] Minor — cosmetic or non-functional