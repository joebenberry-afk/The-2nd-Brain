---
id: n-b542cf0cfa
kind: gotcha
at: 2026-10-23T10:13:09Z
source: agent
tags:
  - windows
  - crlf
checked: uncheckable
checked_at: 2026-11-25T18:00:02Z
checked_why: "The config half is true (`* text=auto`, autocrlf=true). Whether Git Bash sed -i turns CRLF into LF needs a throwaway-file test, which I can't run read-only. GNU sed normally keeps the \\r, so the claim may depend on the tool. [.gitattributes: '* text=auto' plus per-path overrides; git config core.aut"
checked_sha: 8edd97e9a46e
---

Git Bash sed -i rewrites CRLF files as LF (whole-file churn in FG, where .gitattributes is * text=auto and core.autocrlf=true). Edit CRLF files with Python bytes reads/writes instead.
