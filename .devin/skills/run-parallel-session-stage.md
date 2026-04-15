# Skill: Run Parallel Session Stage

Run a batch of independent tasks as parallel Devin child sessions, wait for all to complete, and report unified results. Invoke this skill once per stage of work.

## Arguments

This skill expects `$ARGUMENTS` to be a path to a JSON file describing the stage. Create this JSON file before invoking the skill.

**JSON schema:**

```json
{
  "stage_name": "Stage 1 — Unit/Integration Evals",
  "repo": "visa-workshop/Visa-Agent-Demo",
  "branch": "main",
  "timeout_seconds": 600,
  "sessions": [
    {
      "title": "Categorizer Fraud Evals",
      "prompt": "Checkout branch main. Run: python -m pytest tests/evals/test_categorizer_fraud.py -v. Report pass/fail and any failures.",
      "tag": "eval-s1-categorizer-fraud"
    }
  ]
}
```

- `stage_name` (required): Human-readable name for this stage, used in status messages.
- `repo` (required): Repository in `owner/repo` format. Applied to all child sessions.
- `branch` (required): The git branch each child session should check out.
- `timeout_seconds` (optional, default 600): Max seconds to wait for all sessions to settle.
- `sessions` (required): Array of 1+ session specs. Each must have `title`, `prompt`, and `tag`.

## Procedure

Follow every step below in order. Do not skip steps.

### Step 1 — Parse and validate the stage definition

1. Read the JSON file at the path provided in `$ARGUMENTS`.
2. Validate that `stage_name`, `repo`, `branch`, and `sessions` (non-empty array) are present.
3. Validate that every session entry has `title`, `prompt`, and `tag`.
4. If validation fails, send a blocking message to the user explaining what is missing and stop.
5. Send a non-blocking message to the user: `"Starting {stage_name}: launching {N} parallel sessions against branch {branch}."`

### Step 2 — Launch all child sessions in a single batch

1. Use `devin_session_create` with:
   - `repos`: `["{repo}"]`
   - `sessions`: Map each session spec to `{ "prompt": "{prompt}", "title": "{title}", "tags": ["{tag}", "parallel-stage"] }`
2. This MUST be a single `devin_session_create` call containing all sessions — do NOT create them one at a time.
3. Record all returned session IDs. Remember: the IDs returned do NOT include the `devin-` prefix — you must prepend `devin-` when using them with other tools.

### Step 3 — Wait for all sessions to settle

1. Use `devin_session_gather` with:
   - `session_ids`: All session IDs from Step 2 (with `devin-` prefix)
   - `timeout_seconds`: The value from the stage definition (default 600)
   - `poll_interval_seconds`: 15
2. If `devin_session_gather` times out, identify which sessions are still running using the returned statuses.
3. For any session still running after timeout, use `devin_session_interact` with `action: "terminate"` to kill it. Count terminated sessions as failed.

### Step 4 — Collect results from every session

1. For each session ID, use `devin_session_interact` with `action: "get"` to retrieve the final status and structured output.
2. Classify each session as:
   - **passed**: status is `"exit"` with no error indicators
   - **failed**: status is `"error"`, was terminated, or session output indicates test failures
3. For any failed session, use `devin_session_events` with `action: "search"` and `query: "FAILED"` to extract failure details.
4. Build a results table:

   | # | Title | Tag | Status | Details |
   |---|-------|-----|--------|---------|
   | 1 | ... | ... | PASSED / FAILED | (error details if failed) |

### Step 5 — Report results to the user

1. Count total passed and total failed.
2. Send a **blocking** message to the user with:
   - Stage name and overall verdict: `"{stage_name}: {passed}/{total} PASSED"` or `"{stage_name}: FAILED — {failed}/{total} sessions failed"`
   - The full results table from Step 4
   - For failed sessions: include the error output / failure details
   - A clear statement of whether it is safe to proceed to the next stage

### Step 6 — Set exit status

1. If ALL sessions passed, report that the stage completed successfully and the user may proceed to the next stage.
2. If ANY session failed, report the failures clearly. Do NOT proceed to any subsequent work — the user must decide how to handle failures (retry, fix, or skip).
