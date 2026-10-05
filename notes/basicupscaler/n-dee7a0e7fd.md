---
id: n-dee7a0e7fd
kind: note
at: 2026-10-02T20:13:13Z
source: agent
---

Slint 1.18.1 popups (BU Task 9 fix, dfa8ec5): if/for content of a PopupWindow is built INSIDE show_popup, before show_popup takes the focus off the opener and stores it as the refocus target (window.rs:2033-2171/2245); a focus() in such a child's init is undone and Escape refocuses a dead element. Never focus in init; BU's controls ask a private InitialFocus global (asked/granted, global changed handler) and focus in a changed handler one turn later. Also: a component's own change trackers init AFTER its init code (rust.rs:1720-1735) and component roots are always inlined, so a value bumped in init never fires that component's changed handler. TextInput/Text already clip glyphs to their own geometry in 1.18.1 (FIXME may drop it).
