# Engineering Handbook
## Branching
- `main` is protected.
- Feature branches: `feat/<topic>`, `fix/<bug>`, `chore/<task>`.

## Commits (Conventional)
Examples:
- `feat(orchestrator): add dry-run scale action`
- `fix(policy): correct cooldown parsing`
- `chore(ci): cache docker layers`
- `docs(runbook): add incident rollback steps`

## Pull Requests
- Keep PRs small (≤300 changed lines when feasible).
- CI must pass (lint, unit, build, chart-lint, deploy-dev in later phases).
- 2 approvals required on `main`.

## Code Style
- Go: golangci-lint.
- Python: ruff + pytest.
- Node: eslint + prettier + vitest/jest.

## Security
- No plaintext secrets. Use GitHub Actions secrets & Kubernetes secrets.
- 2FA mandatory for contributors.
- Image signing with cosign (Phase 10).

## Documentation
- ADRs in `/docs/adr` using MADR template.
- Runbooks in `/docs/runbooks`.
- Design diagrams in `/docs/design`.
