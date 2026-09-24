/**
 * V3 payload-order probe (S2 capture-ordering evidence).
 *
 * Loaded only by `scripts/v3_matched_arms.py --order-probe`, which runs it twice
 * around `v3_request_capture_extension.ts`:
 *
 *   -e v3_capture_order_probe.ts -e v3_request_capture_extension.ts
 *   -e v3_request_capture_extension.ts -e v3_capture_order_probe.ts
 *
 * The probe REPLACES the provider payload with a marker key. Because OMP's
 * `emitBeforeProviderRequest` walks the loaded extensions in load order and
 * threads the payload through each handler's return value, the capture must see
 * the marker only in the first arrangement. That is the empirical check that
 * loading the capture last makes it observe everything earlier extensions
 * (including Second Brain) did to the request.
 *
 * Inert without `V3_ORDER_PROBE_MARKER`, so it can never affect a measurement run.
 */

interface OrderHost {
  on(
    event: "before_provider_request",
    handler: (event: { type: "before_provider_request"; payload: unknown }) => unknown,
  ): void;
}

export default function captureOrderProbe(pi: OrderHost): void {
  const marker = process.env["V3_ORDER_PROBE_MARKER"] ?? "";
  if (marker === "") return;
  pi.on("before_provider_request", (event) => {
    const obj =
      event.payload !== null && typeof event.payload === "object"
        ? (event.payload as Record<string, unknown>)
        : {};
    obj["v3_order_probe_marker"] = marker;
    return obj;
  });
}
