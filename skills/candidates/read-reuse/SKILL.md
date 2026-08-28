---
name: read-reuse
status: candidate
candidate_id: skill-candidate-c42679a4a39bcc5415ae0671
project_id: 019edaf1f87d9577
source_radar_candidate_id: candidate-76c88737ad58a6a525c959f5
created_at: 2026-08-26T08:57:16.801900+00:00
---

# Purpose

Avoid repeated reads by reusing verified context before reopening unchanged files.

# Positive Triggers

- repeated file reads
- unchanged source requested again

# Negative Triggers

- first read of a changed file
- correctness-critical fresh read

# Inputs

- current task and verified context
- canonical telemetry evidence

# Procedure

1. Check whether verified context already contains the requested source.
2. Reuse unchanged context; otherwise perform one bounded read.
3. Verify the result against the task before continuing.

# Tools

- existing context and read tool

# Safety

Never reuse context after source or task identity changes.

# Verification

Confirm the reused content is sufficient and current before relying on it.

# Output

A bounded read/reuse decision with no automatic installation.

# References

- radar-candidate candidate-76c88737ad58a6a525c959f5
