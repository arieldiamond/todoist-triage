---
name: todoist-triage
description: Triage new Todoist tasks (unsectioned top-level Inbox tasks) using a GTD/ECHO schema - label by context, set priority and deadline, file into Inbox sections / Career & Learning / Reading List, and ask questions via @review. Use when the user asks to process, triage, organize, or label their Inbox, or runs it on a schedule.
---

# Todoist triage

Rules do most of the work; you only judge what the rules cannot. Never guess: ambiguity becomes an `@review` question for the user.
Read `references/schema.md` before classifying (labels, priority, destinations, caps). `references/golden.yaml` has worked examples.
All Todoist access is the `td` CLI via `scripts/triage.py` (no MCP tool schemas needed).

## Workflow (default: dry run, then confirm)
1. `python3 scripts/triage.py fetch` -> prints a run dir. Tasks already labeled `@review` or `@someday` are skipped (pending the user).
   If it says 0 tasks, stop and report "nothing to triage".
2. Read `RUN/needs_llm.json`. For each task decide the fields the rules could not, following the schema, and write `RUN/llm.json`:
   `{"<task id>": {"dest": "Inbox/House | Inbox/Computer/phone | Inbox/Outside | Inbox/Errand | Inbox/To Buy | Career & Learning | Reading List | Inbox (stays)",
   "labels": ["@Context", ...], "priority": "p1-p4", "deadline": "YYYY-MM-DD", "review": "suggest|classify|someday", "comment": "...", "add": ["@next"], "clear_due": true}}`
   Only include keys you are changing; omitted tasks keep the rules' proposal.
   - Include ONLY the minimum: one context label, 0-2 modifiers, never invent steps or deadlines.
   - `review: classify` = unsure where it goes (stays put, `@review`, comment asks the question). `suggest` = classified and moved, comment holds a proposal (merge, first step, split, subtask link, target date). `someday` = label `@someday` + comment; never move to Someday/Maybe.
   - If an existing due date looks like an external deadline, put it in `deadline`, set `clear_due`, and ask for a target date in the comment.
   - Duplicates/merges, renames, deletes: propose in a comment only.
3. `python3 scripts/triage.py plan RUN` -> writes `RUN/plan.md`. Show the user a short summary (counts, the `@review` questions, anything surprising).
4. After the user approves (or the mode is auto): `python3 scripts/triage.py apply RUN` previews; add `--yes` to execute. `--only "Title" ...` limits it.
5. `python3 scripts/triage.py digest [--post]` -> focus list (1 critical, 3 quick wins, queue counts) with task links. `--post` also sets those tasks due today (so they show in Today) and comments the digest on the Focus task.
Undo: `python3 scripts/triage.py undo RUN [--yes]` restores labels, priority, dates, and location (comments are not deleted).

## Modes
- **dry-run** (default; scheduled runs start here): steps 1-3, report, change nothing.
- **apply-with-confirm**: steps 1-4 after the user says yes.
- **auto**: only when the user has said so explicitly (`install-schedule --auto` / `TRIAGE_AUTO=1`); the daily job then applies confident items if `triage.py eval --split test --min 0.9` passes.

## Hard rules
- Scope: unsectioned top-level Inbox tasks only (`scope.braindump` in rules.yaml adds an optional second capture project). Never touch shared projects, Personal, Someday/Maybe, Reading List content, or sectioned Inbox tasks.
- Never delete, merge, rename, or complete tasks. Never move anything into Someday/Maybe.
- Explicit rules (always applied, even to Claude's output): an `!` anywhere in the title -> p1; a task with `pay` -> p1 and due today unless it already has a due date or deadline. These are exempt from the p1 cap.
- Caps: <=3 open p1 (the script downgrades extra to p2, except the two user rules above), the daily focus sets at most 4 due-today dates (1 critical + 3 quick wins; see caps in rules.yaml), only on tasks with no due date, and releases yesterday's unfinished picks it set.
- Priority numbers in the API are inverted (4 = p1); the script converts, so never hand-write numeric priority.
- Missing labels/sections/projects: run `triage.py setup` (dry-run, then `--yes` with the user's OK). Never let `td` auto-create labels (they become "shared").
- User-supplied dates (e.g. a deadline they tell you) go in `config/facts.local.yaml`, not in the rules. Personal rule changes go in `config/rules.local.yaml`; private golden rows in `references/golden.local.yaml`.

## Maintaining
- After the user resolves `@review` items, read how they resolved them (see `references/schema.md` "Resolutions") and add new rows to `references/golden.yaml` and keywords to `config/rules.yaml`. Run `triage.py eval` after every rule change.
- `triage.py eval --split test` scores rules against held-out golden rows; rows with `needs_claude: true` are excluded (they need judgment).
