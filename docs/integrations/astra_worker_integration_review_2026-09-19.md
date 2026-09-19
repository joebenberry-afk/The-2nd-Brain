# Independent review — integration staging (verbatim)
Preserved from the reviewer payload. Integration follows this text step by step;
nothing here is applied automatically.

## Q1 verdict
ONLY_ACCEPTED_OUTCOME_RECONCILIATION

## Q1 patch text (worker_recovery.py contract)
VERDICT ON recover_attempt(): ONLY-ACCEPTED-OUTCOME-RECONCILIATION. worker_recovery.py:288-316 unconditionally retains protection when logical_outcome is NULL/unresolved, independently of quiescence. The newly added recover() dispatcher reaches release_interrupted_attempt(), but that path is not yet safe: wanted = resources or sorted(attested) cannot detect an omitted resource; missing generations can match each other; generation 0 is collapsed by truthiness; and the transition consumes the host lifecycle sequence. The six existing tests use an accepted completed outcome and lifecycle_sequence=1 by default, not the reported interrupted state.

The minimum sound evidence contract needs a separately recorded COMPLETE resource census, not a resource list inferred from the attestations that happen to exist. The census below is explicitly an operator inspection, with method and observation; it is not a fabricated host inventory. Its resources must include the executor/process scope as well as every outstanding owner job, disposal/advisor operation, isolation backend, capture/commit operation, or other writer-capable resource found by that inspection. The release request selects the census receipt and cannot shrink its resource set. A census without evidence establishing completeness must not be recorded. Software cannot manufacture completeness from an incomplete historical DB.

Unknown generation is a missing prerequisite, not a wildcard. If the actual interrupted row has host_generation NULL, this patch refuses release. An independently preserved launch/binding record identifying that exact attempt and generation is needed before the strict release contract can be met; neither an operator-selected generation nor None == None establishes that fact. Do not retrospectively invent a worker_bind callback.

PATCH: worker_recovery.py. Replace the module description with a description distinguishing accepted-outcome reconciliation from interrupted ownership release. Add the following helpers and census recorder, and replace release_interrupted_attempt() and recover() with the exact text below. Existing RECOVERY_SCHEMA is sufficient; no new table or dependency is needed.


def _generation(value: object) -> int:
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    raise RecoveryError(
        "GENERATION_MISMATCH", "a recorded, non-negative host generation is required"
    )


def _interrupted_row(
    conn: sqlite3.Connection, attempt_id: str, host_generation: int
) -> dict[str, Any]:
    if type(host_generation) is not int or host_generation < 0:
        raise RecoveryError("GENERATION_MISMATCH", "supply the exact integer host generation")
    rows = _rows(conn, project_id=None, task_id=None, attempt_id=attempt_id)
    if not rows:
        raise RecoveryError("ATTEMPT_NOT_FOUND", "no worker attempt matches that attempt id")
    row = rows[0]
    if _generation(row.get("host_generation")) != host_generation:
        raise RecoveryError("GENERATION_MISMATCH", "host generation does not match this attempt")
    if row.get("access_intent") != "mutating":
        raise RecoveryError("BINDING_MISMATCH", "this is not a mutating ownership attempt")
    if (
        row.get("logical_outcome") not in (None, "unresolved")
        or row.get("executor_settled") != 0
        or row.get("cleanup_complete") != 0
        or row.get("lifecycle_sequence") != -1
        or row.get("state") not in ("SUBMITTED", "WORKING", "UNRESOLVED")
    ):
        raise RecoveryError(
            "USE_SETTLEMENT_RECONCILIATION",
            "interrupted release requires no accepted outcome or host lifecycle receipt",
        )
    if row.get("writer_ownership") not in ("held", "quarantined", "released"):
        raise RecoveryError("BINDING_MISMATCH", "invalid writer ownership state")
    return row


def _inventory_binding(row: dict[str, Any]) -> dict[str, Any]:
    binding = {
        key: row.get(key)
        for key in (
            "task_id", "attempt_id", "packet_sha256", "project_id", "worktree_id",
            "worktree_root", "host_session_id", "native_attempt_id", "native_job_id", "agent_id",
        )
    }
    binding["host_generation"] = _generation(row.get("host_generation"))
    return binding


def _write_recovery_event(
    conn: sqlite3.Connection, record: dict[str, Any], recorded_at: str
) -> dict[str, str]:
    blob = json.dumps(record, sort_keys=True)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    event_id = f"r-{digest}"
    conn.execute(
        "INSERT OR IGNORE INTO worker_recovery_events("
        "event_id,attempt_id,host_generation,kind,resource,method,actor,"
        "payload_sha256,payload_json,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (
            event_id, record["attempt_id"], record["host_generation"], record["kind"],
            None, record.get("method"), record["actor"], digest, blob, recorded_at,
        ),
    )
    return {"event_id": event_id, "payload_sha256": digest, "recorded_at": recorded_at}


def _recovery_payload(event: dict[str, Any]) -> dict[str, Any]:
    blob = event["payload_json"]
    if hashlib.sha256(blob.encode("utf-8")).hexdigest() != event["payload_sha256"]:
        raise RecoveryError("INVALID_EVIDENCE", "recorded evidence digest does not match")
    try:
        payload = json.loads(blob)
    except (TypeError, ValueError) as exc:
        raise RecoveryError("INVALID_EVIDENCE", "recorded evidence is not JSON") from exc
    if not isinstance(payload, dict):
        raise RecoveryError("INVALID_EVIDENCE", "recorded evidence is not an object")
    return payload


def record_resource_inventory(
    home: Path | str | None = None,
    *,
    attempt_id: str,
    host_generation: int,
    actor: str,
    resources: list[str],
    complete: bool,
    method: str,
    observation: str,
    now: datetime | str | None = None,
) -> dict[str, str]:
    """Record a complete operator-observed census; this does not release anything.

    The inspection must establish the full writer-capable resource scope, including
    the executor and any mechanisms that could create further work. Its method and
    observation must identify the retained evidence supporting that conclusion.
    """
    if (
        complete is not True
        or not resources
        or any(not isinstance(resource, str) or not resource.strip() for resource in resources)
        or not actor.strip()
        or not method.strip()
        or not observation.strip()
    ):
        raise RecoveryError("INSUFFICIENT_EVIDENCE", "a complete, evidenced resource census is required")
    wanted = sorted(set(resource.strip() for resource in resources))
    if "executor" not in wanted:
        raise RecoveryError("INSUFFICIENT_EVIDENCE", "the census must include executor quiescence")
    with _connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _interrupted_row(conn, attempt_id, host_generation)
        if row["writer_ownership"] == RELEASED:
            raise RecoveryError("ALREADY_RELEASED", "this attempt no longer owns the resource")
        result = _write_recovery_event(
            conn,
            {
                "kind": "operator-resource-inventory",
                "attempt_id": attempt_id,
                "host_generation": host_generation,
                "binding": _inventory_binding(row),
                "actor": actor,
                "coverage_complete": True,
                "coverage_source": "operator-inspection",
                "resources": wanted,
                "method": method,
                "observation": observation,
            },
            _now(now),
        )
        conn.commit()
        return result


def release_interrupted_attempt(
    home: Path | str | None = None,
    *,
    attempt_id: str,
    actor: str,
    host_generation: int,
    resource_inventory_id: str,
    dry_run: bool = True,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Release ownership on complete quiescence evidence, never on task settlement."""
    if not actor.strip() or not resource_inventory_id:
        raise RecoveryError("INSUFFICIENT_EVIDENCE", "actor and recorded resource inventory are required")
    with _connect(home) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = _interrupted_row(conn, attempt_id, host_generation)
        if row["writer_ownership"] == RELEASED:
            return {"attempt_id": attempt_id, "action": "already-released", "changed": False}
        raw = conn.execute(
            "SELECT * FROM worker_recovery_events WHERE event_id=? AND attempt_id=? "
            "AND kind='operator-resource-inventory'",
            (resource_inventory_id, attempt_id),
        ).fetchone()
        if raw is None:
            raise RecoveryError("INSUFFICIENT_EVIDENCE", "no bound resource inventory was recorded")
        inventory_event = dict(raw)
        inventory = _recovery_payload(inventory_event)
        if (
            inventory.get("binding") != _inventory_binding(row)
            or inventory.get("coverage_complete") is not True
            or inventory.get("kind") != "operator-resource-inventory"
        ):
            raise RecoveryError("BINDING_MISMATCH", "inventory does not cover this exact attempt binding")
        resources = inventory.get("resources")
        if (
            not isinstance(resources, list)
            or not resources
            or any(not isinstance(resource, str) or not resource.strip() for resource in resources)
            or "executor" not in resources
        ):
            raise RecoveryError("INVALID_EVIDENCE", "inventory has no complete resource set")
        wanted = set(resources)
        selected: dict[str, dict[str, Any]] = {}
        for event in _attestations(conn, attempt_id):
            resource = event.get("resource")
            if resource not in wanted or resource in selected:
                continue
            payload = _recovery_payload(event)
            try:
                column_generation = _generation(event.get("host_generation"))
                payload_generation = _generation(payload.get("host_generation"))
            except RecoveryError:
                continue
            if (
                column_generation == host_generation
                and payload_generation == host_generation
                and payload.get("attempt_id") == attempt_id
                and payload.get("kind") == "quiescence"
                and payload.get("resource") == resource
                and all(
                    isinstance(payload.get(key), str) and payload[key].strip()
                    for key in ("actor", "method", "observation")
                )
            ):
                selected[resource] = event
        missing = sorted(wanted - selected.keys())
        if missing:
            return {
                "attempt_id": attempt_id,
                "action": "protection-retained",
                "changed": False,
                "unresolved_conditions": ["no bound quiescence attestation for: " + ", ".join(missing)],
            }
        if dry_run:
            return {
                "attempt_id": attempt_id,
                "action": "release-permitted",
                "changed": False,
                "dry_run": True,
                "resource_inventory_id": resource_inventory_id,
                "executor_settled": False,
                "outcome_rewritten": False,
            }
        updated = _now(now)
        receipt = _write_recovery_event(
            conn,
            {
                "kind": "operator-interrupted-ownership-release",
                "attempt_id": attempt_id,
                "host_generation": host_generation,
                "binding": _inventory_binding(row),
                "actor": actor,
                "host_settlement_observed": False,
                "executor_settled": False,
                "cleanup_complete": False,
                "resource_quiescence_established": True,
                "state": row["state"],
                "logical_outcome": row["logical_outcome"],
                "outcome_rewritten": False,
                "lifecycle_sequence": row["lifecycle_sequence"],
                "resource_coverage": "operator-census-and-bound-quiescence",
                "resource_inventory_id": resource_inventory_id,
                "resource_inventory_sha256": inventory_event["payload_sha256"],
                "resources": sorted(wanted),
                "attestations": [
                    {"event_id": selected[resource]["event_id"],
                     "payload_sha256": selected[resource]["payload_sha256"]}
                    for resource in sorted(wanted)
                ],
            },
            updated,
        )
        changed = conn.execute(
            "UPDATE worker_tasks SET writer_ownership='released',ownership_updated_at=?,updated_at=? "
            "WHERE task_id=? AND attempt_id=? AND writer_ownership IN ('held','quarantined')",
            (updated, updated, row["task_id"], attempt_id),
        )
        if changed.rowcount != 1:
            raise RecoveryError("BINDING_MISMATCH", "ownership changed before recovery")
        conn.commit()
        return {
            "attempt_id": attempt_id,
            "action": "ownership-released-for-interrupted-attempt",
            "changed": True,
            "recovery_event_id": receipt["event_id"],
            "receipt_sha256": receipt["payload_sha256"],
            "executor_settled": False,
            "cleanup_complete": False,
            "state_preserved": row["state"],
            "logical_outcome_preserved": row["logical_outcome"],
            "outcome_rewritten": False,
            "lifecycle_sequence": row["lifecycle_sequence"],
        }


def recover(
    home: Path | str | None = None,
    *,
    attempt_id: str,
    actor: str,
    host_generation: int | None = None,
    resource_inventory_id: str | None = None,
    executor_settled_evidence: dict[str, Any] | None = None,
    cleanup_evidence: dict[str, Any] | None = None,
    dry_run: bool = True,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Choose the recovery kind without converting quiescence into settlement."""
    with _connect(home) as conn:
        rows = _rows(conn, project_id=None, task_id=None, attempt_id=attempt_id)
        if not rows:
            raise RecoveryError("ATTEMPT_NOT_FOUND", "no worker attempt matches that attempt id")
        row = rows[0]
    if row.get("executor_settled") or row.get("logical_outcome") not in (None, "unresolved"):
        return recover_attempt(
            home,
            attempt_id=attempt_id,
            actor=actor,
            host_generation=host_generation,
            executor_settled_evidence=executor_settled_evidence,
            cleanup_evidence=cleanup_evidence,
            dry_run=dry_run,
            now=now,
        )
    if host_generation is None or not resource_inventory_id:
        return {
            "attempt_id": attempt_id,
            "action": "protection-retained",
            "changed": False,
            "unresolved_conditions": ["exact host generation and complete recorded resource inventory are required"],
        }
    return release_interrupted_attempt(
        home,
        attempt_id=attempt_id,
        actor=actor,
        host_generation=host_generation,
        resource_inventory_id=resource_inventory_id,
        dry_run=dry_run,
        now=now,
    )

ADDITIONAL EXACT EDITS:
1. Change host_generation annotations in record_quiescence() and recover_attempt() to int | None. In recover_attempt(), add conn.execute("BEGIN IMMEDIATE") immediately after entering its connection context, before its row read. Replace its current optional generation comparison with:

        if host_generation is not None and _generation(row.get("host_generation")) != _generation(host_generation):
            raise RecoveryError("GENERATION_MISMATCH", "host generation does not match this attempt")

2. inspect_attempt(): expose the recovery records separately from host receipts by adding this member to each attempt result:

                    "recovery_events": [
                        dict(event)
                        for event in conn.execute(
                            "SELECT event_id,kind,host_generation,payload_sha256,payload_json,recorded_at "
                            "FROM worker_recovery_events WHERE attempt_id=? AND kind <> 'quiescence' "
                            "ORDER BY recorded_at,event_id",
                            (attempt,),
                        )
                    ],

Also include payload_json in its existing SELECT from worker_lifecycle_receipts. Historical mixed-table operator receipts must remain visible with their actual kind; do not delete or rewrite them to look native.

3. worker_protocol.py reap(): immediately after row = dict(raw), before the protected-writer branch, add:

            if row.get("access_intent") == "mutating" and row.get("writer_ownership") == "released":
                continue

This is necessary for the exact SUBMITTED/NULL case: otherwise the released historical attempt falls through to the legacy SUBMITTED redelivery/failure branch after lease expiry. It must not dispatch old work after C is admitted. State/outcome remain unchanged by the release.

CLI PATCH:
Change lease_quiesce's --host-generation argument to type=int, required=True. Change lease_recover's --host-generation argument to type=int, default=None. Add:

    lease_inventory = wps.add_parser(
        "lease-inventory", parents=[home_parent], help="record a complete interrupted-resource census"
    )
    lease_inventory.add_argument("--attempt", dest="attempt_id", required=True)
    lease_inventory.add_argument("--host-generation", type=int, required=True)
    lease_inventory.add_argument("--actor", required=True)
    lease_inventory.add_argument("--resource", dest="resources", action="append", required=True)
    lease_inventory.add_argument("--complete", action="store_true", required=True)
    lease_inventory.add_argument("--method", required=True)
    lease_inventory.add_argument("--observation", required=True)
    lease_inventory.add_argument("--json", action="store_true")
    lease_recover.add_argument("--inventory", dest="resource_inventory_id", default=None)

Add lease-inventory to the handler's command set. Before its lease-quiesce branch add:

            elif args.worker_plane_command == "lease-inventory":
                payload = worker_recovery.record_resource_inventory(
                    home,
                    attempt_id=args.attempt_id,
                    host_generation=args.host_generation,
                    actor=args.actor,
                    resources=args.resources,
                    complete=args.complete,
                    method=args.method,
                    observation=args.observation,
                )

In its worker_recovery.recover(...) call add:

                    resource_inventory_id=args.resource_inventory_id,

No --resources override belongs on lease-recover. Record the census, record one evidenced quiescence attestation per census resource with the exact generation, then call lease-recover --attempt ... --host-generation ... --inventory <recorded-event-id>, first without and then with --apply.

This interrupted patch does not set COMPLETED, does not alter NULL/unresolved, does not set executor_settled or cleanup_complete, and does not add or consume a host lifecycle receipt. Its truthful release evidence lives in worker_recovery_events with a distinct kind. The accepted-outcome path remains a separate existing contract; its permissive host-observation and any-attestation validation still deserves separate hardening and is not proof of interrupted recovery.

## Q1 required tests
- test_interrupted_release_requires_full_census_and_preserves_history: use the real migrated schema/registered worktree pattern from tests/test_writer_admission.py, or repair the recovery fixture to use host_generation INTEGER, access_intent='mutating', lifecycle_sequence=-1, state='SUBMITTED', logical_outcome=NULL, executor_settled=cleanup_complete=0. Bind a known integer generation in the fixture without generating a fake lifecycle receipt. Record a complete evidenced census containing executor, owner-jobs and isolation-handle; record all three exact-generation quiescence attestations. Verify normal admission B is WORKTREE_WRITER_BUSY before apply; dry-run changes neither ownership nor receipts; apply releases ownership; state remains SUBMITTED, outcome remains NULL, both booleans remain 0 and lifecycle_sequence remains -1; no worker_lifecycle_receipts row is added. Decode/hash the recovery event and assert kind=operator-interrupted-ownership-release, host_settlement_observed=false, executor_settled=false, outcome_rewritten=false, and references to the census and all three attestation digests. Verify C is admitted to the same canonical worktree, expired reaping does not redeliver A, and repeated recovery cannot affect C. Also exercise the reaper-produced UNRESOLVED/unresolved historical state rather than treating it as COMPLETED.
- test_interrupted_release_refuses_partial_attestation: same exact interrupted row and complete census of executor, owner-jobs and isolation-handle, but record only executor and isolation-handle quiescence. Call the normal recover() dispatcher with the census ID and dry_run=False. Assert protection-retained with owner-jobs missing, ownership still held/quarantined, historical fields unchanged, no interrupted-release event and no lifecycle receipt. A bare request with no inventory must likewise refuse; it must never derive the required resource set from the two attestations already present.
- test_interrupted_release_refuses_wrong_or_unknown_generation: use integer generation 7 and a valid census for that binding. A request for generation 8 must raise GENERATION_MISMATCH without a mutation. Correct-generation requests with one resource attested only for generation 8 or with a NULL generation must remain protected. Include generation 0 as a valid exact generation that does not match NULL; an attempt whose recorded generation is NULL must refuse even if its attestations also have NULL. Keep a different attempt/generation on the same task/worktree and assert no stale recovery receipt can release it. Update old string fixtures such as gen-1 to actual integer protocol generations; those strings masked the production INTEGER-versus-recovery-TEXT mismatch.

## Q2 barrier verdict
Current snapshot is only partially corrected. The original OM_CANARY_HOLD_ISOLATION_UNTIL block delayed notification, not release work. Its replacement OM_CANARY_HOLD_RELEASE_UNTIL now genuinely gates releaseIsolation() before capture/commit/cleanup, but one-shot/fallback cleanup invokes cleanupHandle() directly and bypasses that gate. The deferred finally branch still re-registers isolation-handle: attempt-settlement.ts:140 skips that resource because the original isolationRelease.promise is already pending, and that branch never settles the original promise. Both non-deferred finally and releaseIsolation resolve isolationRelease in finally even when cleanup rejects, allowing false settled observations. The latest worktree.ts cleanupIsolation change correctly propagates ordinary isoStop/fs.rm failures; however the runner's unconditional resolve still hides them. A failed cleanup should yield cleanupState='failed' and releasePermitted=false, not rewrite an already accepted task outcome to failed.

The wait is asynchronous: its setTimeout yields to the event loop. trackCleanups attaches callbacks and returns; it does not await the held promise or block unrelated dispatch. Earlier/result-accepted snapshots and their extension callbacks can run during the hold; only the final successful isolation observation must remain unavailable. The owning A execution/lifecycle release may itself await the barrier and may retain its task concurrency permit. Therefore B must be submitted as a separate normal dispatch while A is backgrounded (or from another eligible session), not queued sequentially behind A. The Brain tool_call hook runs prepareWorkerTaskInput before native spawning/semaphore execution, and admit_worker_attempt rejects held/quarantined canonical writers. A queue delay is not B-refusal evidence.

The current sentinel is checked once before entering the loop and repeatedly while waiting. A pre-existing file skips the wait entirely and produces no hold-finish record. The path comes from process-wide environment state; there is no in-code attempt/generation binding. Coordinator naming is an external convention, not replay protection. Timeout currently proceeds with real work and held=false; that is not itself a fabricated cleanup, but it cannot establish signal-before-cleanup in an A->B->C demonstration. The patch below makes stale signal/timeout fail closed and binds a fresh signal path to native attempt, generation and a per-run nonce.

Additional consuming-side defect: extension index.ts:1609-1619 maps running to completed. The initial pending-resource publication can therefore become a durable COMPLETED outcome before resultAccepted. The exact correction is included below; without it, the demonstration has a separate false-success path.

## Q2 patch text (barrier)
READ-ONLY PATCH TEXT AGAINST THE LAST READ SNAPSHOT. Keep the original one-time trackCleanups registration of isolationRelease.promise. Do not register a second promise under isolation-handle. The latest cleanupIsolation() error-propagation change may remain as read; the runner must now forward its rejection instead of resolving in finally.

1. isolation-runner.ts: add this import:

import { randomUUID } from "node:crypto";

2. Inside runIsolatedSubprocess(), keep the existing declarations through releasePromise. Immediately after those declarations add the following code. OM_CANARY_HOLD_RELEASE_UNTIL now specifies a PATH PREFIX, not an already existing signal file. The coordinator must wait for hold-begin and create the exact emitted file. The prefix itself must not exist; the actual signal additionally includes native identity, generation and a fresh nonce.

	const holdPrefix = process.env.OM_CANARY_HOLD_RELEASE_UNTIL;
	const holdNonce = holdPrefix ? randomUUID() : undefined;
	let holdPromise: Promise<void> | undefined;
	const awaitReleaseSignal = (): Promise<void> => {
		if (!holdPrefix) return Promise.resolve();
		holdPromise ??= (async () => {
			const identity = opts.baseOptions.settlement?.snapshot();
			if (!identity) throw new Error("Isolation hold requires an attempt settlement identity");
			const holdFile = `${holdPrefix}.${encodeURIComponent(identity.attemptId)}.${identity.generation}.${holdNonce}`;
			const binding = JSON.stringify({
				agentId: opts.agentId,
				attemptId: identity.attemptId,
				generation: identity.generation,
				holdFile,
			});
			const assertAbsent = async (file: string): Promise<void> => {
				try {
					await fs.stat(file);
				} catch (error) {
					if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
					throw error;
				}
				throw new Error(`Stale isolation hold sentinel: ${file}`);
			};
			await assertAbsent(holdPrefix);
			await assertAbsent(holdFile);
			const deadline = Date.now() + 600_000;
			__traceIsolation(`isolation:hold-begin:${binding}`);
			for (;;) {
				if (Date.now() >= deadline) {
					__traceIsolation(`isolation:hold-timeout:${binding}`);
					throw new Error(`Isolation release signal timed out: ${holdFile}`);
				}
				try {
					const signal = await fs.stat(holdFile);
					if (!signal.isFile()) throw new Error(`Isolation signal is not a file: ${holdFile}`);
					if (Date.now() >= deadline) throw new Error(`Isolation release signal timed out: ${holdFile}`);
					__traceIsolation(`isolation:release-signal:${binding}`);
					return;
				} catch (error) {
					if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
				}
				await new Promise<void>(resolve => setTimeout(resolve, 200));
			}
		})();
		return holdPromise;
	};

3. Keep releaseBase() unchanged. Replace cleanupHandle() and releaseIsolation() with this exact text. No work promise is converted from rejection into successful settlement.

	const cleanupHandle = (): Promise<void> => {
		cleanupPromise ??= (async () => {
			await awaitReleaseSignal();
			await releaseBase();
			if (retainWorkspace) {
				throw new Error("Isolation workspace retained; cleanup is not established");
			}
			if (handle) await cleanupIsolation(handle);
		})();
		return cleanupPromise;
	};
	const releaseIsolation = (): Promise<void> => {
		if (!releasePromise) {
			releasePromise = (async () => {
				await awaitReleaseSignal();
				if (!handle || retainWorkspace) {
					await cleanupHandle();
					return;
				}
				try {
					let patchResult: IsolationPatchArtifacts;
					try {
						patchResult = await writeIsolationPatch(handle.mergedDir, taskBaseline, opts.artifactsDir, opts.agentId);
					} catch (captureErr) {
						retainWorkspace = true;
						const retained = await retainIsolationWorkspace(handle.mergedDir, handle.backend);
						throw new Error(
							renderIsolationError({
								kind: "patch-capture-failed",
								message: captureErr instanceof Error ? captureErr.message : String(captureErr),
								retainedDir: retained.dir,
								sidecarMissing: !retained.sidecarOk,
							}),
						);
					}
					AgentRegistry.global().setHistory(opts.agentId, {
						patchPath: patchResult.patchPath,
						nestedPatchPaths: patchResult.nestedPatchPaths,
					});
					const commitResult = await commitToBranch(
						handle.mergedDir,
						taskBaseline,
						opts.agentId,
						opts.description,
						undefined,
					);
					AgentRegistry.global().setHistory(opts.agentId, {
						patchPath: patchResult.patchPath,
						branchName: commitResult?.branchName,
						nestedPatchPaths: patchResult.nestedPatchPaths,
					});
				} finally {
					await cleanupHandle();
				}
			})();
			void releasePromise.then(isolationRelease.resolve, isolationRelease.reject);
		}
		return releasePromise;
	};

4. Keep this registration exactly once, before ensureIsolation/runSubprocess, as in the corrected snapshot:

	opts.baseOptions.settlement?.trackCleanups([
		{ resource: "isolation-handle", work: isolationRelease.promise },
	]);

5. After the existing successful deferred-cleanup wait and before the post-run branch capture, add a gate for that independent capture/commit path. The exact resulting section is:

		if (deferredCleanup && result.exitCode === 0) {
			await deferredCleanup;
		}
		if (result.exitCode === 0) {
			await awaitReleaseSignal();
		}
		if (opts.mergeMode === "branch" && result.exitCode === 0) {

The rest of that branch and subsequent capture code stays unchanged.

6. Replace the outer catch/finally at the end of runIsolatedSubprocess() with the following. The deferred chain is created once, is not re-registered under an already pending key, and both fulfillment and rejection reach the ORIGINAL isolationRelease promise. The non-deferred path also reaches that original promise only through the real work's result.

	} catch (err) {
		if (!handle || retainWorkspace) isolationRelease.reject(err);
		return rememberAgentArtifacts(opts.buildFailureResult(err));
	} finally {
		if (retainWorkspace) {
			isolationRelease.reject(new Error("Isolation workspace retained; cleanup is not established"));
		}
		if (
			handle &&
			!retainWorkspace &&
			!releasePromise &&
			!(opts.baseOptions.keepAlive !== false && AgentLifecycleManager.global().has(opts.agentId))
		) {
			const cleanup = deferredCleanup ? deferredCleanup.then(cleanupHandle) : cleanupHandle();
			void cleanup.then(isolationRelease.resolve, isolationRelease.reject);
			if (deferredCleanup) {
				trackLateCleanup(cleanup, {
					agentId: opts.agentId,
					resource: "isolation",
				});
			} else {
				await cleanup;
			}
		}
	}
}

7. brainstem/prime-extension/src/index.ts: replace the whole const outcome ternary inside the attempt_settlement observer with:

              const outcome: AsyncJobLifecycleObservation["status"] =
                snapshot.resultAccepted ? snapshot.outcome : "running";

The existing observeWorkerAttempt consumer already maps status running to a NULL lifecycle outcome and skips emitWorkerCompletion for running. This fixes the producing side without changing the wire type: running is explicitly part of AsyncJobLifecycleObservation.status in types/prime.d.ts:39-51.

FOCUSED PROOF TO RUN AFTER INTEGRATION: exercise a kept-alive release and a one-shot release with a real pending isolation handle; timer/independent dispatch must progress before the sentinel is created and capture/commit/cleanup must not start. Exercise deferred-cleanup fulfillment and rejection, verifying the one original isolation resource leaves pending exactly once, with failed rather than settled on rejection. Exercise a pre-existing prefix/signal and a bounded-timeout test; neither may perform release work or produce releasePermitted=true. Inject isoStop failure with successful directory removal and separately directory-removal failure; both must leave cleanupState failed and ownership protected. Feed an initial running/resultAccepted=false snapshot through the actual extension observer and assert durable logical_outcome remains NULL and no completion is emitted. These patch-text changes have not been executed in this read-only audit; the reported canary load and six tests were parent-run checks of the prior snapshot, not proof of these new branches.

## Required A->B->C evidence
- Pin the actual loaded canary and extension source hashes and capability version; record project_id, canonical worktree_id/root, Brain task_id/attempt_id, packet hash, host session, native attempt ID, generation, native job/agent ID, source tool-call ID and sourceIndex. Keep callback secrets out of public evidence.
- A: capture the real pending snapshot for that identity with isolation-handle in cleanupPendingResources, cleanupState pending and releasePermitted false; capture hold-begin containing the fresh bound signal pathname before any release/capture/commit/cleanup work starts. A must be a real mutating attempt using the normal admission path, not a hand-edited ownership row.
- While the same hold is active, submit B through the ordinary task tool -> extension prepareWorkerTaskInput -> worker admission path against the same canonical worktree. Preserve the request, actual WORKTREE_WRITER_BUSY refusal, absence of native B dispatch/side effects, and A's still-held/quarantined ownership. Semaphore waiting, a timeout, a direct probe of the SQL predicate, or a different worktree is not B-refusal evidence.
- After B's refusal, record the coordinator's creation of the exact fresh signal file and the host's release-signal observation with the same native attempt/generation. A stale file, hold timeout, requested kill or bare unlock does not satisfy this step.
- Capture actual release work completion after the signal: capture/commit as applicable, successful backend stop and successful directory removal (or equivalent actual release), then fulfillment of the original tracked isolation promise. A trace inside finally is not sufficient; failed teardown must publish failed, never settled.
- Capture the final host snapshot with resultAccepted=true, no pending or failed cleanup resources and releasePermitted=true. Preserve the extension's observation-to-callback mapping and the exact monotonic lifecycle sequence. Record second-brain.worker-lifecycle-accepted and read the committed worker_lifecycle_receipts payload/digest plus authoritative worker_tasks row; observing a callback being sent or a local published snapshot is not durable acceptance.
- Verify ownership becomes released only in the same durable acceptance transition after actual cleanup. Then submit C through normal admission and preserve its newly admitted attempt identity and native start evidence, proving it targets the same canonical worktree. Show the sequence pending -> B refusal -> release signal -> actual cleanup fulfillment -> accepted durable host receipt/ownership release -> C admission, using identities and causal handoffs as well as timestamps.
- Keep interrupted operator recovery as a separate demonstration: exact generation + complete evidenced census + per-resource attestations -> operator-interrupted-ownership-release event -> C admission. Its evidence must explicitly show executor_settled=false, historical NULL/unresolved outcome preserved and host lifecycle sequence unchanged. Never substitute that operator event for the host-observation-accepted step in the A->B->C settlement demonstration.

## Named false-success risks
- Current interrupted release does not directly mark COMPLETED and its payload names operator-recovery-interrupted with executor_settled=false/outcome_rewritten=false. That portion is truthful. However its placement in worker_lifecycle_receipts and incremented lifecycle_sequence makes it look native in lease-inspect, which currently omits payload kind, and can collide with a later genuine lifecycle sequence. The proposed dedicated recovery-event record removes that ambiguity and preserves the host sequence.
- The current inferred resource set passes any nonempty partial attestation set. Adding resource_coverage='operator-asserted' documents uncertainty but does not establish completeness. A separately evidenced complete census is required; the proposed census is still trusted operator evidence, not an automatic proof of OS/process quiescence. If completeness cannot actually be established, recovery must remain refused.
- Unknown generation is not an exact generation. None/None and truthiness-based comparisons are unsafe; valid generation 0 must remain distinct from missing. The real worker_tasks schema stores an INTEGER whereas worker_recovery_events stores TEXT, so canonical comparison must not accidentally reject known exact generations or accept absence.
- An unlocked SUBMITTED attempt otherwise enters reap's legacy redelivery/failure logic. This can relaunch stale work after a new writer is admitted or rewrite the preserved historical state; the narrow reaper exclusion in the patch is required.
- Recovery currently reads before beginning a write transaction and updates by task_id. A concurrent admission/rebinding can replace the row after the evidence check; BEGIN IMMEDIATE before the authoritative read and attempt-qualified update prevent stale evidence releasing another attempt.
- The new real barrier protects only releaseIsolation unless cleanupHandle and post-run capture are gated as well. A successful kept-alive demonstration alone would miss the one-shot path. The original deferred promise must be resolved/rejected from the actual cleanup chain, not replaced with a deduplicated registration.
- Resolving isolationRelease in finally converts cleanup failure into success. Parent's new cleanupIsolation rejection propagation is necessary but insufficient until those unconditional resolves are removed. Per-resource failure must keep releasePermitted false while preserving the accepted logical outcome.
- The extension currently maps a running snapshot to completed, which is then accepted by ingest_worker_lifecycle and can emit worker completion before result acceptance. This is a concrete false-success path independently of recovery; use the included running-preserving mapping.
- Current sentinel reuse can skip holding, and current timeout can proceed without a release signal. Neither proves A->B->C ordering. The proposed fresh identity-bound pathname, stale-prefix rejection and fail-closed timeout prevent silent fixture passes; the coordinator must consume the emitted pathname rather than creating the prefix.
- The existing accepted-outcome recover_attempt path accepts source='host-observation' JSON with weak binding checks and treats any attestation as cleanup coverage. Its successful result is not evidence that the primary interrupted case is covered. The interrupted patch deliberately does not use those inputs to invent an accepted outcome or executor settlement.
- No working-tree edits, builds or tests were run by this read-only audit. Verification here is source-to-consumer tracing, including the authoritative SQL release/admission/reap paths and the current teardown implementation. The supplied patch text needs the focused proof cases above after integration; parent's reported six passing tests and canary load remain valid reports about their exercised snapshot, not about the proposed patch.
