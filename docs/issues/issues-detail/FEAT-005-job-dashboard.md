# FEAT-005 Job Group Lock

## Metadata
- Type: feature
- Priority: high
- Status: resolved
- Area: scheduler

## Problem Statement
The recommendation jobs in the same functional group can overlap in execution. This creates avoidable bursts of external API calls and repeated hits to the same web pages.

## Current Behavior
Currently the discovery and tracked stocks recommendation jobs can run at the same time. This can lead to a too high API hit and same web page hit frequency.

## Desired Behavior

When one of the jobs {"discovery stocks recommendation", "tracked stocks recommendation"} is running then no other job from this group will be started.

If job #1 from the group is running and job #2 becomes due, job #2 must remain in waiting state and must not start until the group lock is released.

There is only one scheduler instance running at a time.

## Scope
- In scope:
	- Group-level mutual exclusion for jobs in the same configured job group.
	- Waiting behavior for due jobs blocked by an active group lock.
	- Lock release behavior on normal completion and crash/failure.
	- Configuration contract for group definitions.
- Out of scope:
	- Distributed locking across multiple scheduler instances.
	- Database schema changes outside what is needed for scheduler state handling.

## Functional Requirements

### FR-1 Group Mutual Exclusion
- A job group lock is acquired when a job in that group starts running.
- While the lock is held, any other due job in the same group must not start.
- Jobs outside that group are unaffected.

### FR-2 Waiting Behavior
- A blocked job stays pending/waiting and is started immediately after the group lock is released.
- No concurrent execution is allowed among jobs in the same group.

### FR-3 Lock Release
- The group lock must be released when the running job reaches a terminal state:
	- success/completed,
	- failure/error,
	- crash/unexpected termination detected by scheduler flow.

### Job Crash

If job #1 dies, the lock held by it is released. Job #2 that was waiting for job #1 can be started.

### FR-4 Startup/Restart Safety
- On scheduler startup, in-memory lock state must start clean.
- No stale in-memory lock may block execution after process restart.

### FR-5 Deterministic Candidate Selection
- When the lock is released, the next runnable job must be selected deterministically from due jobs in that group.
- Selection order is earliest due time first.

### FR-6 Validation and Error Handling
- Invalid group configuration must fail fast at startup with actionable error messages.
- Scheduler must continue running unaffected groups if one group has no due jobs.

## Configuration

The groups are defined in configuration. The job is identified by the job ID (apscheduler_jobs.id).

Initial group definition:

```python
job_groups = [
		{
				"job_group": "recommendations_workflows",
				"jobs": ["discovery_workflow", "tracked_stock_batch"],
		}
]
```

Configuration rules:
- Group names must be unique.
- Job IDs in a group must be unique.
- Unknown job IDs must raise a startup validation error.

## Observability Requirements
- Log when a group lock is acquired and released.
- Log when a due job is blocked by group lock, including blocking job ID and group name.
- Log when a waiting job is finally started after lock release.

## Acceptance Criteria
- AC-1: If discovery workflow starts first and tracked stock batch becomes due while discovery is running, tracked stock batch does not start concurrently.
- AC-2: After discovery workflow completes, tracked stock batch is started immediately without requiring manual intervention.
- AC-3: If discovery workflow crashes, the lock is released and tracked stock batch can start.
- AC-4: Jobs in other groups continue to run according to their schedules while recommendations group lock is held.
- AC-5: Invalid job group configuration fails at startup with clear validation messages.
- AC-6: If multiple jobs are waiting in the same group, the job with the earliest due time starts first.

## Test Plan (Minimum)
- Unit tests:
	- lock acquisition and release for success/failure/crash flows,
	- blocked job remains pending while lock is held,
	- deterministic next-job selection once lock is released,
	- config validation failures for malformed groups/unknown job IDs.
- Integration tests:
	- simulate overlapping due times for discovery_workflow and tracked_stock_batch and verify no overlap,
	- simulate crash path and verify lock release plus immediate start of next eligible job,
	- simulate multiple waiting jobs and verify earliest-due-time-first ordering.

## Implementation Summary

### Root Cause
The scheduler started each APScheduler job independently and had no group-level mutual exclusion. As a result, due jobs in the discovery/tracked pair could launch concurrently.

### Resolution
- Added scheduler job-group configuration in config.
- Added scheduler startup validation for job-group configuration (unknown job IDs, duplicates, invalid structure).
- Implemented in-memory group lock acquisition/release for single-scheduler runtime.
- Implemented waiting queue for blocked jobs with deterministic selection by earliest due time.
- Implemented immediate rescheduling of the next waiting job when lock is released.
- Added release handling for normal terminal states and crash/liveness-failure paths.
- Added unit tests covering lock queueing, release behavior, ordering, and config validation.

### Remaining Risks / Follow-up
- This feature is intentionally scoped to a single scheduler instance and does not provide distributed locking.
- Immediate restart relies on APScheduler modify(next_run_time=now) behavior and should remain covered by integration tests.
