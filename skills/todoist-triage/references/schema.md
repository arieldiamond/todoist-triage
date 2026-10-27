# Todoist triage schema (v1.0, defaults)

## Principles (ADHD guardrails)
1. **Process once, move on.** A task is "processed" when it has an Inbox section or has left the Inbox. The skill never re-sorts processed tasks.
2. **Max 3 decisions per task:** context, priority, destination. Nothing else is required.
3. **Surface, don't list.** The output is a short focus list, not a full inventory: max 1 critical + 3 quick wins.
4. **Just-in-time decomposition.** Projects get an outcome (parent) + at most 1-3 next-step subtasks. Remaining ideas live in the parent's description as a parking-lot list, NOT as tasks.
5. **Unsure -> @review, never guess.** Ambiguous tasks stay unsectioned in the Inbox with @review.
6. **Caps:** <=3 p1 open at once; Daily focus: 1 critical + 3 quick wins get due=today (only if they have no due date); the script releases yesterday's unfinished picks.

## Context labels (ECHO) - exactly ONE per actionable task
| Label | Meaning |
|---|---|
| @Errand | Outside the house (stores, post office, appointments in person) |
| @Computer/phone | Anything digital: email, orders, applications, calls, cancellations, study |
| @House | Physical, inside the house: clean, organize, fix, find things |
| @Outside | Physical, on the property: garden, yard, garage/shed |

Keep `@buy` as a modifier (an item to purchase) IN ADDITION to its context (online = Computer/phone, store = Errand), and place it in the Inbox "To Buy" section.
Context labels are kept even when a task moves to Someday/Maybe, so context survives a project change.
Reading items carry no context label.

## Modifier labels (0-2 per task)
| Label | Meaning | Status |
|---|---|---|
| @next | The single next step of a multi-step project (not every task) | existing, repurposed |
| @quick | <=5 min. Momentum builder. |
| @waiting | Blocked on someone/something |
| @review | Skill unsure; needs human decision |
| @someday | Skill SUGGESTS Someday/Maybe; awaiting user decision. Task stays put; one-line comment gives the reason. Separate from @review. |
| @focus | Needs 30+ min uninterrupted (study, applications) |

## Dates
- **Due date** = target date (when I plan to do it). **Deadline** = drop-dead date (Todoist deadline field, `td task update --deadline`).
- Skill sets a deadline only when a real one is visible (existing due date on an externally-deadlined task, date in title/description). Never invents one.
- If an existing due date looks like a hard deadline, move it to deadline and ask for a target date in a comment.
- Appointments use a due date with time (no separate calendar label).

## Priority
- **p1 Critical:** deadline <=7 days, or money/health/legal/job consequence. Max 3.
- **p2 Important:** deadline within ~2 weeks, or moves a current goal (job search, certs).
- **p3 Normal:** actionable, no pressure.
- **p4 Not committed:** untriaged or Someday. Any p4 outside Someday/Maybe = unprocessed.

## Destinations
Sections mirror context; labels carry context too (redundant on purpose).
- **Inbox** (actionable singles + project parents; the long-term capture point): sections Computer/phone, House, Outside, Errand, To Buy. Projects = parent task in the section of the first step's context.
- **Career & Learning**: job search, certifications, interview prep. Sections only for long-lived pursuits.
- **Personal** (optional): routines and waiting-for; not looked at regularly. The skill never reads it except to find the Focus task if `focus.project` points there.
- **Reading List**: books/articles/videos you've committed to
- **Someday/Maybe**: not committed (keeps its context label). SKILL NEVER MOVES TASKS HERE; user does, after reviewing @someday suggestions.
- Stay unsectioned in Inbox + @review: ambiguous
- Ignore: all shared projects.
- New tasks go straight to the Inbox (an optional second capture project can be set in `scope.braindump`).

## Keyword rules (deterministic first pass)
| Pattern | Action |
|---|---|
| email, call, text, cancel, sign up, submit, apply, order, pay, schedule, research | @Computer/phone |
| pick up, return, drop off, buy (in store), post office | @Errand |
| clean, wash, put away, organize, find, mend, declutter, sort | @House |
| plant, transplant, water, mow, rake, shed, garage, shears | @Outside |
| read a chapter / read (committed) | Reading List (no context) |
| listen, watch (no commitment) | @someday suggestion |
| "decide if", "consider", "maybe", "someday" | @someday suggestion (skill never moves to Someday/Maybe itself) |
| trailing "?" | question: @quick if one step, else @review |
| cancel, refill, pay, text, email, call, schedule + <=1 step | @quick |

## Filters (surfacing)
- Now: `(overdue | today | p1) & !@waiting`
- Deadlines soon: `deadline before: +7 days`
- Quick wins: `@quick & !p4`
- Per context: `@House & !p4 & !@waiting` (etc.)
- Review queue: `@review`
- Someday queue: `@someday & !##Someday/Maybe`

## Scope (v1)
Touches ONLY unsectioned top-level Inbox tasks. Never reads/changes shared projects, Personal, Reading List, Someday/Maybe (other than placing a processed task into Reading List / Career & Learning / Inbox sections).

## Out of scope for v1
Legacy tasks in Inbox/Personal/Someday (one-time cleanup, separate pass).

## Priority notes
- Explicit rules: `!` anywhere in the title -> p1. A task with `pay` -> p1 and due today unless it already has a due date or deadline. Both are exempt from the p1 cap.
- Health items (`always_p1` words, e.g. insurance) are p1 regardless of date. Money items (`money_by_deadline` words, e.g. tax) are p1 only within 7 days of the deadline, else p2. Unknown deadline: p1 + reminder + @review.
- A prerequisite inherits the priority of the task that depends on it; propose the parent/subtask link in a comment, never apply it.


## Skill-to-user communication
- Never merge, rename, or delete tasks automatically. Merge candidates get @review + a task comment proposing the merge.
- Questions for the user go in a comment on the task (e.g. "Deadline unknown?"), alongside @review.
- The daily digest is a comment on the Focus task (1 critical + 3 quick wins, with links).

## Known facts
User-supplied dates (deadlines Todoist doesn't hold) live in `config/facts.local.yaml`; see `config/facts.example.yaml`.
