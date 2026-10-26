---
id: n-9bb0e9ac1f
kind: note
at: 2026-10-25T20:29:18Z
source: agent
---

Northstar eval c25 premise flawed: fixture calculateTax Math.round(cents*rate) has real float bug (200*0.0725=14.4999 -> 14). n9 run 2 fixed it with proving test and failed unchanged-check. v1.2: make fixture tax integer-exact.
