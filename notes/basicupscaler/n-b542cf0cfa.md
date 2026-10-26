---
id: n-b542cf0cfa
kind: gotcha
at: 2026-10-23T10:13:09Z
source: agent
tags:
  - windows
  - crlf
---

Git Bash sed -i rewrites CRLF files as LF (whole-file churn in FG, where .gitattributes is * text=auto and core.autocrlf=true). Edit CRLF files with Python bytes reads/writes instead.
