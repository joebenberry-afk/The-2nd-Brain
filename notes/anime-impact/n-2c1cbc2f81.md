---
id: n-2c1cbc2f81
kind: note
at: 2026-11-08T21:24:36Z
source: agent
evidence:
  - tools/hand_pose.gd
evidence_sha:
  - tools/hand_pose.gd=981c7096ad4d
---

Godot 4.7: a new class_name script (e.g. tools/hand_pose.gd HandPose) is invisible to other scripts until 'godot --headless --path . --import' refreshes the class cache; symptom: Parse Error: Could not find type "HandPose". Also: killing godot via TaskStop leaves Windows child processes; use ps -W winpid + taskkill //F //PID.
