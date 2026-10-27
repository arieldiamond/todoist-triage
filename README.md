# todoist-triage

A Claude Code skill that sorts new Todoist Inbox tasks for you, using a GTD-inspired schema built for people who over-organize (it was made by and for an ADHD brain).

It labels each task by context, sets a priority, files it into an Inbox section, and posts a short daily focus list: **1 critical task + 3 quick wins**, with links. Anything it isn't sure about is left in place with an `@review` label and a question in a comment. It never deletes, renames, merges or completes tasks.

Not an official Todoist product.

## How it works

1. **Rules first.** Keyword rules (`config/rules.yaml`) resolve most tasks with no LLM call.
2. **Claude for the rest.** Leftovers are judged in one batch by Claude, following `references/schema.md`.
3. **Plan, then apply.** A plan is written first. Applying logs every change, and `undo` restores labels, priority, dates and location.
4. **Digest.** The focus list is posted as a comment on a "Focus" task and the picks get a due date of today.

### The schema (ECHO)
Context labels, exactly one per task: `@Errand` (outside the house), `@Computer/phone` (anything digital), `@House` (physical, inside), `@Outside` (physical, on the property). Modifiers: `@quick`, `@next`, `@waiting`, `@focus`, `@buy`, `@review`, `@someday`. Priorities: p1 critical (max 3 open), p2 important, p3 normal, p4 not committed. Due date = your target; deadline = drop-dead date. Full details in [`skills/todoist-triage/references/schema.md`](skills/todoist-triage/references/schema.md).

Built-in rules include: `!` in a title makes it p1; a task containing `pay` is p1 and due today unless it already has a date; ambiguous tasks become `@review` questions rather than guesses.

## Requirements
- [Todoist CLI](https://github.com/Doist/todoist-cli) (`td`), logged in with `td auth login`
- Python 3.9+ and `pip install pyyaml`
- Optional: the `claude` CLI, for judging tasks the rules can't resolve (without it they stay in the Inbox for you)

## Install
```
/plugin marketplace add arieldiamond/todoist-triage
/plugin install todoist-triage@arieldiamond-skills
```
Or copy `skills/todoist-triage` into `~/.claude/skills/`.

## First run
```
cd skills/todoist-triage
python3 scripts/triage.py setup          # preview the labels/sections/projects it will create
python3 scripts/triage.py setup --yes
python3 scripts/triage.py fetch          # new Inbox tasks -> a run directory
python3 scripts/triage.py plan RUN       # show what it would do (nothing is written to Todoist)
python3 scripts/triage.py apply RUN      # preview; add --yes to apply
python3 scripts/triage.py undo RUN --yes # reverse a run
```
Or just ask Claude: "triage my Todoist inbox". Start in dry-run until you trust it.

## Run it daily
```
python3 scripts/triage.py install-schedule --at 06:00 --yes          # dry-run + digest
python3 scripts/triage.py install-schedule --at 06:00 --auto --yes   # also apply confident changes
```
On macOS this installs a launchd agent (a missed run fires when the Mac wakes); elsewhere it prints a cron line. Auto mode applies only when the rules still score at least 90% on the held-out split of the golden dataset, and ambiguous tasks still go to `@review`.

## Make it yours
Defaults live in `config/rules.yaml`. Put your changes in `config/rules.local.yaml` (merged over the defaults, gitignored): keywords, section and project names, the Focus task's location, the P1/money/health word lists. Dates Todoist doesn't know go in `config/facts.local.yaml` (see `facts.example.yaml`). Your own examples go in `references/golden.local.yaml`. After any rule change run `python3 scripts/triage.py eval`.

State (runs, logs, the day's focus picks) is kept in `~/.todoist-triage`, or `$TODOIST_TRIAGE_HOME`.

## Known limits
- Labels and sections are created by `setup`; renamed sections need a matching `sections` entry in your local rules.
- The saved-filter syntax (`deadline before: +7 days`, `@someday & !##Someday/Maybe`) is created but not verified in every Todoist plan.
- Tested on macOS only.

## License
MIT
