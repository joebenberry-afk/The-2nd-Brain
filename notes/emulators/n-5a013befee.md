---
id: n-5a013befee
kind: gotcha
at: 2026-11-15T21:01:00Z
source: agent
errors:
  - SetTerminateResult result=0x2a2 (2162-0001)
evidence:
  - src/Eglantine-f7c0cc30ac/docs/system-map/README.md
evidence_sha:
  - src/Eglantine-f7c0cc30ac/docs/system-map/README.md=0f7c296d15ba
tested: "true"
tested_by: agent
tested_at: 2026-11-15T21:01:00Z
tested_sha: 312646e4aac2
checked: moved
checked_at: 2026-11-25T17:59:39Z
checked_why: "The move-handle abort still holds: the code keeps a COPY handle and README 'Not fixed' (line 96) still cites 0x2a2 / 2162-0001. The stated blockers are gone. SignalAfterGpu now holds shared_from_this and QueueBackingRelease captures the GPU. Nx2ClearSparseBacking clears only the owner's handler, and"
checked_sha: 312646e4aac2
---

Eglantine nx2_gsv: pushing the session as a move handle in ReturnRawSession makes Fire Emblem Fortune's Weave abort at boot
Abort is in nn::gsv::BootWithRemoteMemory under BootGraphicsSystem, SetTerminateResult 0x2a2 (2162-0001). Reverted. Sessions cannot be destroyed until INx2GpuSession::SignalAfterGpu and QueueBackingRelease stop handing raw `this`/KEvent* to the GPU thread, and the process-wide Nx2SetSparseBacking handler (video_core/nx2.h:399) is cleared only by its owner. Written up in docs/system-map/README.md, "Not fixed".
