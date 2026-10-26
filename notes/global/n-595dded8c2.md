---
id: n-595dded8c2
kind: gotcha
at: 2026-10-21T07:34:44Z
source: agent
---

DSH can estimate session spend from tokenUsage, but the Platform wallet balance needs a grant this desktop profile does not have

The spend pill lives at C:\Users\assas\Documents\dsh-spend (bundle @local/dsh-spend): a composer-dock entry priced from the tokenUsage projection. The Harness profile's only credential is client-connection/browser-session; the account service reads deepseek-account-platform/default, so remote.account.getBalance returns null (signed-out) and the widget hides the balance. Sign in from the sidebar account menu to enable it.

DeepSeek peak rates per 1M (deepseek-flash): cache hit $0.006, cache miss $0.30, output $1.20; off-peak is exactly half. deepseek-v4-pro: 0.044 / 1.32 / 3.96. My first cut used the off-peak column as peak, which halved every estimate; the tests now pin both columns. Session cost at 50.8M cache-read + 0.31M miss + 0.20M output is $0.6403 at peak. The account's topped-up balance on the platform page was $3.14.
