# Order validation requirements

- REQ-1: `validate_order(order)` returns false when `order.quantity <= 0`.
- REQ-2: `validate_order(order)` returns false when `order.items` is an empty array.
- REQ-3 (verification): before reporting completion, the implementation MUST
  pass `node verify.js` (the Requirement Ledger verification step).
