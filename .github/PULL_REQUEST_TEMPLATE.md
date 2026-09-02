# Pull Request

<!--
Thanks for opening this PR! Please fill in the sections below — reviewers use them to size the change.
The detailed contribution guide is in CONTRIBUTING.md.
-->

## What & why

<!--
A 2-4 sentence summary of the change and the problem it solves.
Reference any related issue with `Closes #N` or `Refs #N`.
-->

## How to verify

<!--
Steps for a reviewer to reproduce the change locally. Include the exact commands
and the URLs they should hit. For UI changes attach before/after screenshots.
-->

## Risk & rollback

<!--
What could break? How do we revert? Note schema changes, model retraining,
new env vars, or dependency bumps here.
-->

## Checklist

- [ ] Branch is rebased on `origin/main`
- [ ] `cd backend && pytest -q` is green
- [ ] `cd frontend && npm run lint` is green
- [ ] Docs updated (README / ARCHITECTURE / CHANGELOG)
- [ ] No secrets, model artefacts, or `.env` files staged
- [ ] UI changes include a screenshot or screen recording
- [ ] Conventional Commit messages

/cc @AbeerChaturvedi
