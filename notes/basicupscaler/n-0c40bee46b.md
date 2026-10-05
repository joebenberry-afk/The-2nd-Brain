---
id: n-0c40bee46b
kind: note
at: 2026-10-02T17:51:34Z
source: agent
---

Slint 1.18.1 FocusScope quirk (BU Task 9, 1f4bb01): a disabled FocusScope ignores ALL focus events incl. FocusOut (i-slint-core items/input_items.rs focus_event returns FocusIgnored when !enabled), so a control disabled while focused keeps has-focus=true after focus moves on; a has-focus&&kb-focus ring stays/returns. Fix: changed enabled => { if !enabled { kb-focus = false } }. TextInput is not affected. Also: repeated rows created after their parent's init never see a changed handler fire (ChangeTracker init evaluates current value) - take initial focus in the row's own init too.
