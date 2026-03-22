---
name: save
description: Quick save with snapshot and auto-generated filename
user_invocable: true
---

Save current work:

1. Create a snapshot via `manage_snapshots(action="save", name="auto_[timestamp]")`
2. Save file via `save_file()`
3. Report save path and snapshot name
