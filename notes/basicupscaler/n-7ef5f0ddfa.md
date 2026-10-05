---
id: n-7ef5f0ddfa
kind: note
at: 2026-10-02T10:51:18Z
source: agent
---

Godot 4.7.2: SceneTree root is NOT inside the tree during _initialize; nodes added there never get ENTER_TREE. Skeleton3D adds a PhysicalBoneSimulator3D (a SkeletonModifier3D, trips N8) only on entering the tree; verify_worlds now builds in the first _process (godot-worlds f11c1df).
