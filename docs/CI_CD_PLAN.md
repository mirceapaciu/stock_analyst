# CI/CD Plan for in-prem Linux Production Server

## Goals

- Commit changes to the `dev` branch.
- Automatically run tests on `dev` updates.
- Merge from `dev` into `main` through pull requests.
- Automatically deploy to production when `main` is updated.
- Gracefully shut down services before deploying updates.

## Deployment Model

- **Source control and automation**: GitHub repository + GitHub Actions.
- **Production target**: Separate Linux server at in-prem.
- **Runtime**: Docker Compose using `docker-compose-deploy.yml`.
- **Deployment execution**: GitHub Actions self-hosted runner installed on the Linux server.
- **Connectivity model**: Outbound-only from in-prem server to GitHub (HTTPS/443). No inbound access from GitHub cloud to your server is required.

## Current Local Server Configuration (Implemented)

See [local_prod_server.md](deploy/local/local_prod_server.md) for the current local production server setup,
including Docker runtime, self-hosted runner configuration, deployment behavior,
and verification commands.

## Network Constraint Handling (Server Not Publicly Reachable)

- Use a **self-hosted runner** on the production server and run the deploy job on that runner.
- The runner polls GitHub for jobs and executes deployment locally on the same host.
- Do not use SSH-based deployment from GitHub-hosted runners.
- No port forwarding or public exposure of SSH is required for CI/CD.

## Branch Strategy

1. Use `dev` as the active development branch.
2. Use `main` as the production branch.
3. Merge to `main` only via pull requests from `dev`.

## Required Repository Settings

### Branch protection for `dev`

- Require status checks to pass before merge.
- Require branch to be up to date before merge.

### Branch protection for `main`

- Require pull request before merge.
- Require status checks to pass before merge.
- Optional but recommended: require at least one review approval.
- Restrict direct pushes to `main`.

### Environment protection for production (recommended)

- Create GitHub Environment: `production`.
- Store deploy workflow controls in this environment (approvals, branch restrictions, optional deploy flags).
- Optional: require manual approval before production deployment.

## CI Pipeline (Dev Branch)

### Trigger

- On push to `dev`.
- On pull requests targeting `dev`.

### Steps

1. Check out code.
2. Set up Python 3.13.
3. Install `uv` and sync dependencies.
4. Run tests:
   - `uv run pytest -m "not integration"`
5. Publish test results/logs as workflow artifacts (optional but useful).

### Expected output

- Fast feedback on every development change.
- Merge to `main` is blocked until CI checks pass.

## Merge Process (`dev` -> `main`)

1. Open pull request from `dev` to `main`.
2. Ensure CI checks are green.
3. Review and merge.
4. Merge commit (or squash) to `main` triggers CD automatically.

## CD Pipeline (Main Branch)

### Trigger

- On push to `main`.

### Runner

- Self-hosted Linux runner labeled for production deploy (example labels: `self-hosted`, `linux`, `prod`).

### Steps

1. Use deployment concurrency lock so only one production deploy runs at a time.
2. Check out latest `main`.
3. Pull/build updated containers.
4. Gracefully stop running service before replacement.
5. Start updated service.
6. Run post-deploy health checks.
7. Mark deployment success/failure and preserve logs.

## Graceful Shutdown and Deployment Sequence

Use a deployment script on the Linux server (for example `scripts/deploy_production.sh`) with this sequence:

1. `docker build -t stock-analysis-app:latest .`
2. `docker compose -f docker-compose-deploy.yml stop -t 45`
3. `docker compose -f docker-compose-deploy.yml up -d --build --remove-orphans`
4. Health check loop (HTTP endpoint or container health status).
5. If health checks fail, return non-zero exit code and optionally roll back.

### Compose-level graceful stop settings

Add these in `docker-compose-deploy.yml` per service:

- `stop_signal: SIGTERM`
- `stop_grace_period: 45s`

This gives the application time to close DB connections, flush writes, and stop cleanly before the container is terminated.

## Rollback Strategy (Recommended)

At minimum:

1. Keep previous image tag available.
2. If deploy health check fails, redeploy previous known-good image.
3. Record rollback event in workflow logs.

Optional improvement:

- Use immutable version tags (for example commit SHA) and maintain a small release history.

## Secrets and Security

- Keep production runtime secrets on the Linux server (for example in `/opt/stock-analyst/.env` with `chmod 600`).
- Use GitHub Environment/Repository secrets only when truly needed by workflows running in GitHub.
- For self-hosted deployment on the same server, avoid storing app runtime API keys in GitHub unless you explicitly want centralized cloud secret management.
- Do not store secrets in repository files.
- Restrict self-hosted runner to this repository only.
- Run runner under a non-root user with minimum required privileges.

## Workflow Files to Create

- `.github/workflows/ci-dev.yml`
  - Runs tests for pushes/PRs on `dev`.
- `.github/workflows/cd-main.yml`
  - Deploys automatically on `main` push using self-hosted runner.

## Implementation Checklist

1. Create branch protection rules for `dev` and `main`.
2. Provision self-hosted runner on in-prem Linux server.
3. Add GitHub Actions workflows (`ci-dev.yml`, `cd-main.yml`).
4. Add graceful stop settings to `docker-compose-deploy.yml`.
5. Add deployment script with stop -> deploy -> health-check flow.
6. Test full path with a small change:
   - push to `dev` -> CI runs,
   - PR `dev` -> `main`,
   - merge -> auto deploy on production.

## Operational Notes

- Keep integration tests as separate workflow (manual or nightly) to avoid slowing development CI.
- Add notifications (email/Slack/Teams) for deployment success/failure.
- Periodically update runner, Docker, and system packages on the in-prem server.
