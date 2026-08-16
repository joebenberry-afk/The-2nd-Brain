# TASK — e03-log-pipeline

Ops wants a repeatable command that summarizes ONLY the error lines from our daily logs (each error line carries an amount). Output should be mean/min/max of those amounts. We already have scripts/filter.js (regex line filter over files) and scripts/stats.js (CSV summary). We'll re-run this every morning, so the command should be easy to invoke.
