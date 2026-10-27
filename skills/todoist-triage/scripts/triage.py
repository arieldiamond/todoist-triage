#!/usr/bin/env python3
"""Todoist triage: rules first, Claude for leftovers, apply with a log.

  triage.py setup [--yes]                 create missing labels/sections/projects/filters
  triage.py fetch                          new run dir: tasks.json, proposals (rules), needs_llm.json
  triage.py plan RUN [--llm llm.json]      merge Claude overrides -> plan.json + plan.md (no writes to Todoist)
  triage.py apply RUN [--yes] [--only T..] execute the plan (dry-run unless --yes), log to changes.jsonl
  triage.py undo RUN [--yes]               restore labels/priority/dates/location from the log
  triage.py install-schedule [--at HH:MM] [--yes]  daily dry-run via launchd (macOS) or a cron line
  triage.py eval                           score rules against references/golden.yaml (no Todoist access)
  triage.py digest [--run RUN] [--post]    short focus list; --post comments it on the daily Focus task (due today)
Priority note: the API scale is inverted (4 = p1, 1 = p4); this script converts.
"""
import argparse, json, os, re, subprocess, sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_yaml(path):
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def merge(base, over):
    for k, v in over.items():
        base[k] = merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return base


# rules.yaml = shipped defaults; rules.local.yaml / facts.local.yaml = your overrides (gitignored)
CFG = merge(load_yaml(ROOT / 'config' / 'rules.yaml'), load_yaml(ROOT / 'config' / 'rules.local.yaml'))
FACTS = (load_yaml(ROOT / 'config' / 'facts.local.yaml') or {}).get('facts') or []
STATE = Path(os.environ.get('TODOIST_TRIAGE_HOME') or Path.home() / '.todoist-triage')
RUNS = STATE / 'runs'
DEFAULT_CTX = CFG.get('default_context', '@Computer/phone')   # digital catch-all: career items, purchases, short questions
CTX = [c['label'] for c in CFG['context']]
STOP = set('a an the of to for on in at and with my is i'.split())
NEW_LABELS = ['quick', 'waiting', 'review', 'someday', 'focus', 'next', 'buy']
FILTERS = {
    'Now': '(overdue | today | p1) & !@waiting',
    'Deadlines soon': 'deadline before: +7 days',
    'Quick wins': '@quick & !p4',
    'Review queue': '@review',
    'Someday queue': '@someday & !##Someday/Maybe',
}


# ---------- Todoist access ----------
def td(*args, check=True):
    r = subprocess.run(['td', *args], capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"td {' '.join(args)} failed:\n{r.stderr}{r.stdout}")
    return r.stdout


def tasks_in(project):
    out = json.loads(td('task', 'list', '--project', project, '--json', '--all'))
    return out['results']


def name_map(lines):
    m = {}
    for line in lines.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            m[parts[1].strip().lstrip('@')] = parts[0].replace('id:', '')
    return m


def projects():
    return name_map(td('project', 'list'))


def sections(project_id):
    return name_map(td('section', 'list', 'id:' + project_id))


def labels():
    return set(name_map(td('label', 'list')))


# ---------- Rules ----------
def hit(title, kws):
    t = title.lower()
    return [k for k in kws if re.search(r'(?<!\w)' + re.escape(k.strip().lower()) + r'(?:s|es|ed|ing)?(?!\w)', t)]


def next_occurrence(m, d, today):
    y = today.year if (m, d) >= (today.month, today.day) else today.year + 1
    return date(y, m, d)


def propose(title, today=None):
    """Rules-only proposal for one title. status: confident | conflict | needs_llm."""
    today = today or date.today()
    p = {'title': title, 'labels': [], 'dest': None, 'priority': 'p3', 'deadline': None,
         'review': None, 'comment': None, 'status': None}
    if hit(title, CFG['someday']):
        p.update(status='confident', dest='Inbox', labels=['@someday'], priority='p4', review='someday',
                 comment='No commitment signal. Suggest Someday/Maybe? Accept: move it there and remove @someday. Reject: just remove @someday.')
        return p
    if hit(title, CFG['force_llm']):
        p['status'] = 'needs_llm'
        return p
    ctx = [(c['label'], hit(title, c['match'])) for c in CFG['context']]
    ctx = [c for c in ctx if c[1]]
    for lab, words in CFG.get('explicit_context', {}).items():
        if hit(title, words):
            ctx = [c for c in ctx if c[0] == lab]
    career, reading = bool(hit(title, CFG['career'])), bool(hit(title, CFG['reading']))
    for name, (m, d) in CFG['holidays'].items():
        if name in title.lower():
            dl = next_occurrence(m, d, today)
            p['deadline'] = dl.isoformat()
            p['priority'] = 'p1' if (dl - today).days <= 7 else 'p2'
    purchase = bool(hit(title, CFG['buy_verbs']))
    if career:
        p.update(dest=CFG['projects']['career'], labels=[DEFAULT_CTX], priority='p2')
    elif reading:
        p.update(dest=CFG['projects']['reading'])
    elif len(ctx) == 1:
        p.update(dest='Inbox/' + CFG['sections'][ctx[0][0]], labels=[ctx[0][0]])
    elif len(ctx) > 1 and purchase:
        p.update(dest='Inbox/' + CFG['sections'][DEFAULT_CTX], labels=[DEFAULT_CTX])
    elif len(ctx) > 1:
        p['status'] = 'conflict'
        return p
    else:
        p['status'] = 'needs_llm'
        return p
    if purchase and not career:
        p['labels'].append('@buy')
        p['dest'] = 'Inbox/' + CFG['sections']['@buy']
    if hit(title, CFG['focus_verbs']):
        p['labels'].append('@focus')
    if hit(title, CFG['quick_verbs']) and len(re.findall(r'\w+', title)) <= CFG['quick_max_words']:
        p['labels'].append('@quick')
    if title.rstrip().endswith('?') and DEFAULT_CTX in p['labels'] and len(re.findall(r'\w+', title)) <= CFG['quick_max_words'] and '@quick' not in p['labels']:
        p['labels'].append('@quick')   # a short question = send one message / look one thing up
    if hit(title, ['cancel']):
        p['priority'] = CFG['cancel_priority']
    health, money = hit(title, CFG['always_p1']), hit(title, CFG['money_by_deadline'])
    if health or money:
        fact = next((f for f in FACTS if hit(title, [f['match']])), None)
        if fact and fact.get('deadline'):
            p['deadline'] = str(fact['deadline'])
            p['priority'] = 'p1' if (health or (fact['deadline'] - today).days <= 7) else 'p2'
        else:
            p.update(priority='p1', review='suggest',
                     comment='Deadline unknown. Find it and tell me; I will set it as the deadline.')
    if hit(title, CFG['project_words']):
        p.update(review='suggest', comment='Looks like a multi-step project. What is the single first step? I will add only that as the @next subtask.')
    p['status'] = 'confident'
    return user_rules(p)


def user_rules(p):
    """The user's explicit overrides; idempotent, run after rules and after Claude's overrides."""
    t = p['title']
    if CFG['explicit_p1_char'] in t:
        p['priority'] = 'p1'; p['pin_p1'] = True
    if hit(t, CFG['pay_words']):
        p['priority'] = 'p1'; p['pin_p1'] = True
        ex = p.get('existing') or {}
        if not ex.get('due') and not ex.get('deadline') and not p.get('deadline'):
            p['due'] = 'today'
        else:
            p.pop('due', None)   # already has a date: leave it alone
    return p


def toks(s):
    return {w for w in re.findall(r'\w+', s.lower()) if w not in STOP}


def duplicate_ids(pool):
    flagged = set()
    for i, a in enumerate(pool):
        if hit(a['content'], CFG['reading']):
            continue  # recurring habits are not duplicates
        for b in pool[i + 1:]:
            ta, tb = toks(a['content']), toks(b['content'])
            same = a['content'].strip().lower() == b['content'].strip().lower()
            if same or (len(ta & tb) >= 3 and len(ta & tb) / len(ta | tb) >= 0.4):
                flagged |= {a['id'], b['id']}
    return flagged


# ---------- fetch ----------
def work_set():
    bd = []
    if CFG['scope'].get('braindump') and CFG['scope']['braindump'] in projects():
        bd = [t for t in tasks_in(CFG['scope']['braindump']) if not t['parentId']]
    inbox_all = tasks_in(CFG['scope']['inbox'])
    ib = [t for t in inbox_all if not t['parentId'] and not t['sectionId']]
    todo = [t for t in bd + ib if not ({'review', 'someday'} & set(t['labels']))]   # pending the user's answer
    return todo, bd + inbox_all


def cmd_fetch(a):
    today = date.today()
    todo, pool = work_set()
    flagged = duplicate_ids(pool)
    run = RUNS / datetime.now().strftime('%Y%m%d-%H%M%S')
    run.mkdir(parents=True)
    props, need = [], []
    bd_id = projects().get(CFG['scope'].get('braindump') or '')
    for t in todo:
        p = propose(re.sub(r'^\*+|\*+$', '', t['content']), today)
        p.update(id=t['id'], src='Braindump' if t['projectId'] == bd_id else 'Inbox',
                 existing={k: t.get(k) for k in ('labels', 'priority', 'due', 'deadline', 'description')})
        p['duplicate'] = t['id'] in flagged
        props.append(p)
        if p['status'] != 'confident' or p['duplicate'] or p['review']:
            need.append({'id': t['id'], 'title': p['title'], 'description': (t['description'] or '')[:200],
                         'due': (t.get('due') or {}).get('date'), 'rules_status': p['status'],
                         'rules_proposal': {k: p[k] for k in ('dest', 'labels', 'priority', 'review')}, 'duplicate': p['duplicate']})
    json.dump(props, open(run / 'proposals.json', 'w'), indent=1, default=str)
    json.dump(need, open(run / 'needs_llm.json', 'w'), indent=1)
    print(f'run: {run}\ntasks: {len(props)} | rules resolved: {sum(p["status"] == "confident" for p in props)} | for Claude: {len(need)}')
    print(f'Next: Claude reviews {run}/needs_llm.json and writes {run}/llm.json, then: triage.py plan {run}')


# ---------- plan ----------
def cmd_plan(a):
    run = Path(a.run)
    props = json.load(open(run / 'proposals.json'))
    llm = json.load(open(a.llm or run / 'llm.json')) if (a.llm or (run / 'llm.json').exists()) else {}
    for p in props:
        p['by'] = 'rules'
        ov = llm.get(p['id'])
        if ov:
            p['by'] = 'rules+claude'
            for k in ('dest', 'labels', 'priority', 'deadline', 'review', 'comment', 'clear_due', 'reminder'):
                if k in ov:
                    p[k] = ov[k]
            for x in ov.get('add', []):
                if x not in p['labels']:
                    p['labels'].append(x)
            if 'dest' in ov:
                p['status'] = 'confident'
        user_rules(p)
        if p['duplicate'] and not p['review']:
            p.update(review='suggest', comment=p['comment'] or 'Possible duplicate/similar task. Merge?')
        if p['review'] in ('suggest', 'classify') and '@review' not in p['labels']:
            p['labels'].append('@review')
        if p['status'] != 'confident':
            p['dest'] = f"UNRESOLVED ({p['status']})"
    json.dump(props, open(run / 'plan.json', 'w'), indent=1, default=str)
    rows = [f'# Plan for {run.name} (nothing applied)', f'{len(props)} tasks | rules {sum(p["by"] == "rules" for p in props)} | rules+claude {sum(p["by"] != "rules" for p in props)}', '',
            '| src | task | dest | labels | pri | deadline | note |', '|---|---|---|---|---|---|---|']
    for p in props:
        note = ((p['review'] + ': ') if p['review'] else '') + (p['comment'] or '')
        rows.append(f"| {p['src'][0]} | {p['title'][:40]} | {p['dest']} | {' '.join(p['labels'])} | {p['priority']} | {p['deadline'] or ''} | {note[:100]} |")
    (run / 'plan.md').write_text('\n'.join(rows))
    print('\n'.join(rows))


# ---------- apply / undo ----------
def log(run, rec):
    with open(Path(run) / 'changes.jsonl', 'a') as f:
        f.write(json.dumps(rec) + '\n')


def snapshot(j):
    return {'projectId': j['projectId'], 'sectionId': j['sectionId'], 'labels': j['labels'], 'priority': j['priority'],
            'due': (j.get('due') or {}).get('date'), 'deadline': (j.get('deadline') or {}).get('date')}


def cmd_apply(a):
    run = Path(a.run)
    plan = json.load(open(run / 'plan.json'))
    pj = projects()
    inbox_id = pj[CFG['scope']['inbox']]
    secs = sections(inbox_id)
    have = labels()
    open_p1 = len(json.loads(td('task', 'list', '--priority', 'p1', '--personal', '--json', '--all'))['results'])
    tomorrow = (date.today() + timedelta(days=1)).isoformat() + ' 09:00'
    n = 0
    for p in plan:
        if a.only and p['title'] not in a.only:
            continue
        if p['status'] != 'confident' or p['dest'].startswith('UNRESOLVED'):
            continue
        tid = 'id:' + p['id']
        now = json.loads(td('task', 'view', tid, '--json'))
        if now['sectionId']:
            print('SKIP (already sectioned since fetch):', p['title']); continue
        new_labels = sorted({l.lstrip('@') for l in p['labels']} | set(now['labels']))
        missing = [l for l in new_labels if l not in have]
        if missing:
            sys.exit(f'Missing labels {missing}: run triage.py setup --yes first.')
        pri = p['priority']
        if pri == 'p1' and not p.get('pin_p1') and open_p1 >= CFG['caps']['p1_open'] and not now['priority'] == 4:
            pri = 'p2'; p['comment'] = (p['comment'] or '') + f" (p1 cap of {CFG['caps']['p1_open']} reached; set to p2.)"
        elif pri == 'p1':
            open_p1 += 1
        cmds = [['task', 'update', tid, '--labels', ','.join(new_labels)]]
        if p['review'] in (None, 'suggest'):
            cmds[0] += ['--priority', pri]
        if p.get('deadline'): cmds[0] += ['--deadline', p['deadline']]
        if p.get('clear_due'): cmds[0] += ['--no-due']
        if p.get('due') and not (now.get('due') or {}).get('date') and not (now.get('deadline') or {}).get('date'): cmds[0] += ['--due', p['due']]
        fact = next((f for f in FACTS if hit(p['title'], [f['match']]) and f.get('due')), None)
        if fact and not (now.get('due') or {}).get('date'): cmds[0] += ['--due', str(fact['due'])]
        d = p['dest']
        if p['review'] in (None, 'suggest'):
            if d.startswith('Inbox/'):
                cmds.append(['task', 'move', tid, '--project', 'id:' + inbox_id, '--section', 'id:' + secs[d.split('/', 1)[1]]])
            elif d in pj:
                cmds.append(['task', 'move', tid, '--project', 'id:' + pj[d]])
        if p.get('comment'):
            cmds.append(['comment', 'add', tid, '--content', p['comment']])
        if p.get('reminder') or (pri == 'p1' and p['review'] == 'suggest' and not p.get('deadline')):
            cmds.append(['reminder', 'add', tid, '--at', tomorrow])
        print(('APPLY ' if a.yes else 'would  ') + p['title'][:44].ljust(44), '->', d if p['review'] in (None, 'suggest') else 'stays', new_labels, pri)
        if not a.yes:
            continue
        for c in cmds:
            td(*c)
        log(run, {'id': p['id'], 'title': p['title'], 'before': snapshot(now), 'after': snapshot(json.loads(td('task', 'view', tid, '--json'))), 'comment': p.get('comment')})
        n += 1
    print(f'{n} applied' if a.yes else 'dry run (add --yes to apply)')


def cmd_undo(a):
    for line in reversed(open(Path(a.run) / 'changes.jsonl').read().splitlines()):
        c = json.loads(line); b = c['before']; tid = 'id:' + c['id']
        print(('UNDO  ' if a.yes else 'would  ') + c['title'])
        if not a.yes: continue
        upd = ['task', 'update', tid, '--priority', 'p%d' % (5 - b['priority'])]
        upd += ['--labels', ','.join(b['labels'])] if b['labels'] else ['--no-labels']
        upd += ['--due', b['due']] if b['due'] else ['--no-due']
        upd += ['--deadline', b['deadline']] if b['deadline'] else ['--no-deadline']
        td(*upd)
        td('task', 'move', tid, '--project', 'id:' + b['projectId'], *(['--section', 'id:' + b['sectionId']] if b['sectionId'] else ['--no-section']))
    print('Comments added by the run were NOT deleted.' if a.yes else 'dry run')


# ---------- setup / digest / eval ----------
def cmd_setup(a):
    pj, have = projects(), labels()
    todo = [('label', l) for l in NEW_LABELS + [x.lstrip('@') for x in CTX] if l not in have]
    if CFG['projects']['career'] not in pj: todo.append(('project', CFG['projects']['career']))
    existing = sections(pj[CFG['scope']['inbox']])
    todo += [('section', s) for s in set(CFG['sections'].values()) if s not in existing]
    cur = td('filter', 'list')
    todo += [('filter', n) for n in FILTERS if n not in cur]
    for kind, name in todo:
        print(('CREATE ' if a.yes else 'would create ') + kind, name)
        if a.yes:
            if kind == 'label': td('label', 'create', '--name', name)
            elif kind == 'project': td('project', 'create', '--name', name)
            elif kind == 'section': td('section', 'create', '--name', name, '--project', 'id:' + pj[CFG['scope']['inbox']])
            else: td('filter', 'create', '--name', name, '--query', FILTERS[name])
    print('nothing to do' if not todo else ('done' if a.yes else 'dry run (add --yes)'))


FOCUS = CFG.get('focus', {'title': 'Focus', 'project': 'Inbox'})   # daily digest comment lands on this task


def pick_focus():
    """Critical (p1 or deadline <=7d) + quick wins, counts from caps in rules.yaml."""
    ts = json.loads(td('task', 'list', '--personal', '--json', '--all'))['results']
    ts = [t for t in ts if t['content'].lstrip('* ') != FOCUS['title']]
    soon = (date.today() + timedelta(days=7)).isoformat()
    dl = lambda t: (t.get('deadline') or {}).get('date') or '9'
    crit = sorted([t for t in ts if t['priority'] == 4 or dl(t) <= soon], key=lambda t: (-t['priority'], dl(t)))[:CFG['caps']['focus_critical']]
    skip = {'review', 'someday', 'waiting'}
    taken = {t['id'] for t in crit}
    quick = sorted([t for t in ts if 'quick' in t['labels'] and t['priority'] > 1 and t['sectionId'] and t['id'] not in taken
                    and not skip & set(t['labels'])], key=lambda t: -t['priority'])[:CFG['caps']['focus_quick']]
    counts = Counter(l for t in ts for l in t['labels'] if l in ('review', 'someday'))
    return crit, quick, counts


def link(t):
    return f"[{t['content']}]({t['url']})"


def digest_text(run=None, crit=None, quick=None, counts=None):
    if crit is None:
        crit, quick, counts = pick_focus()
    out = [f'Focus for {date.today():%a %b %d}', '', 'Critical:']
    out += [f"- {link(t)} (p{5 - t['priority']}{', deadline ' + t['deadline']['date'] if t.get('deadline') else ''})" for t in crit] or ['- nothing critical']
    out += ['', 'Quick wins:'] + [f'- {link(t)}' for t in quick] if quick else []
    out += ['', f"Queues: {counts.get('review', 0)} to review, {counts.get('someday', 0)} someday suggestions"]
    if run:
        plan = json.load(open(Path(run) / 'plan.json'))
        done = (Path(run) / 'changes.jsonl').exists()
        out += ['', f'Triage: {len(plan)} new task(s) ' + ('sorted automatically (undo: triage.py undo ' + Path(run).name + ').' if done else f'waiting. Nothing applied. Tell Claude "apply the plan {Path(run).name}" to apply.')]
        out += [f"- {p['title'][:50]} -> {p['dest']}" + (f" ({p['review']}: {(p['comment'] or '')[:60]})" if p['review'] else '') for p in plan[:8]]
    return '\n'.join(out)


def set_focus_due(chosen):
    """Put today's picks in Today (due today) and release earlier picks this script set that are still untouched.
    Re-running on the same day keeps the day's picks instead of releasing them."""
    state_f = RUNS.parent / 'focus.json'
    state = json.load(open(state_f)) if state_f.exists() else {'date': None, 'ids': []}
    today = date.today().isoformat()
    keep = {t['id'] for t in chosen}
    ids = []
    for tid in state['ids']:
        r = subprocess.run(['td', 'task', 'view', 'id:' + tid, '--json'], capture_output=True, text=True)
        if r.returncode:
            continue  # completed or deleted
        if state['date'] == today and tid in keep:
            ids.append(tid)   # still today's pick
        elif ((json.loads(r.stdout).get('due') or {}).get('date')) == state['date']:
            td('task', 'update', 'id:' + tid, '--no-due')
    for t in chosen:
        if t['id'] in ids:
            continue
        if not t.get('due'):   # never override a due date the user (or another rule) set
            td('task', 'update', 'id:' + t['id'], '--due', 'today')
            ids.append(t['id'])
    json.dump({'date': today, 'ids': ids}, open(state_f, 'w'))
    return ids


def cmd_digest(a):
    crit, quick, counts = pick_focus()
    text = digest_text(a.run, crit, quick, counts)
    print(text)
    if not a.post:
        return
    ids = set_focus_due(crit + quick)
    print(f'set {len(ids)} task(s) due today')
    found = next((t for t in tasks_in(FOCUS['project']) if t['content'].lstrip('* ') == FOCUS['title'] and not t['parentId']), None)
    if found:
        td('task', 'update', 'id:' + found['id'], '--due', 'today')
        tid = found['id']
    else:
        tid = json.loads(td('task', 'add', FOCUS['title'], '--project', FOCUS['project'], '--due', 'today', '--uncompletable',
                            '--description', 'Daily digest from the todoist-triage skill. Comments only; this task stays due today.', '--json'))['id']
    td('comment', 'add', 'id:' + tid, '--content', text)
    print('posted to Focus task', tid)


def cmd_eval(a):
    local = ROOT / 'references' / 'golden.local.yaml'   # your private rows, if any; otherwise the shipped sample
    gold = yaml.safe_load((local if local.exists() else ROOT / 'references' / 'golden.yaml').read_text())['tasks']
    F, deferred, n, misses = Counter(), 0, 0, []
    for g in gold:
        if a.split and g.get('split') != a.split: continue
        p = propose(g['title'], date(2026, 10, 23))
        if p['status'] != 'confident' or g.get('needs_claude'):
            deferred += 1; continue
        n += 1
        if p['review'] in ('suggest', 'classify') and '@review' not in p['labels']: p['labels'].append('@review')
        chk = {'dest': p['dest'] == g['dest'], 'labels': sorted(p['labels']) == sorted(g['labels']), 'priority': p['priority'] == g['priority'],
               'deadline': p['deadline'] == (str(g['deadline']) if g.get('deadline') else None), 'review': bool(p['review']) == bool(g.get('review'))}
        for k, v in chk.items(): F[k] += v
        if not all(chk.values()): misses.append((g['title'], [k for k, v in chk.items() if not v]))
    print(f'rules resolved {n}, deferred to Claude {deferred}')
    for k in ('dest', 'labels', 'priority', 'deadline', 'review'): print(f'  {k:9} {F[k]}/{n}')
    for t, ks in misses: print('  miss:', t, ks)
    if a.min is not None and n and min(F[k] / n for k in ('dest', 'labels', 'priority', 'deadline', 'review')) < a.min:
        sys.exit(f'eval below {a.min:.0%}: not auto-applying')


def cmd_schedule(a):
    """Write (macOS) a launchd agent, or print a cron line, that runs daily.sh with this Python and the dir holding `td`."""
    import plistlib, shutil
    td_bin = shutil.which('td')
    if not td_bin: sys.exit('td CLI not found on PATH. Install it and run `td auth login` first.')
    hh, mm = (int(x) for x in a.at.split(':'))
    sh = ROOT / 'scripts' / 'daily.sh'
    path = ':'.join(dict.fromkeys([str(Path(td_bin).parent), str(Path(shutil.which('claude') or td_bin).parent), '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin']))
    env = {'PATH': path, 'TRIAGE_PY': sys.executable, 'TODOIST_TRIAGE_HOME': str(STATE), 'TRIAGE_AUTO': '1' if a.auto else '0'}
    (STATE / 'logs').mkdir(parents=True, exist_ok=True)
    if sys.platform != 'darwin':
        print(f"{mm} {hh} * * * env PATH={path} TRIAGE_PY={sys.executable} TRIAGE_AUTO={int(a.auto)} /bin/bash {sh} >> {STATE}/logs/daily.log 2>&1   # add with `crontab -e`")
        return
    label = 'com.todoist-triage.daily'
    plist = Path.home() / 'Library' / 'LaunchAgents' / f'{label}.plist'
    data = {'Label': label, 'ProgramArguments': ['/bin/bash', str(sh)], 'EnvironmentVariables': env,
            'StartCalendarInterval': {'Hour': hh, 'Minute': mm},
            'StandardOutPath': str(STATE / 'logs' / 'daily.log'), 'StandardErrorPath': str(STATE / 'logs' / 'daily.err')}
    print(f'{"writing" if a.yes else "would write"} {plist}\n  daily at {a.at}, python {sys.executable}, td {td_bin}\n  auto-apply ' + ('ON' if a.auto else 'OFF (dry-run + digest)') + '')
    if a.yes:
        plist.write_bytes(plistlib.dumps(data))
        subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{label}'], capture_output=True)
        subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(plist)], check=True)
        print('loaded. Stop with: launchctl bootout gui/$(id -u)/' + label)
    else:
        print('add --yes to install')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest='cmd', required=True)
    for name, fn in [('setup', cmd_setup), ('fetch', cmd_fetch), ('plan', cmd_plan), ('apply', cmd_apply), ('undo', cmd_undo), ('digest', cmd_digest), ('eval', cmd_eval), ('install-schedule', cmd_schedule)]:
        s = sp.add_parser(name); s.set_defaults(fn=fn)
        if name in ('plan', 'apply', 'undo'): s.add_argument('run')
        if name == 'plan': s.add_argument('--llm')
        if name == 'digest': s.add_argument('--post', action='store_true'); s.add_argument('--run')
        if name in ('setup', 'apply', 'undo', 'install-schedule'): s.add_argument('--yes', action='store_true')
        if name == 'install-schedule': s.add_argument('--at', default='06:00', help='HH:MM local time'); s.add_argument('--auto', action='store_true', help='apply confident changes automatically (default: dry-run + digest)')
        if name == 'apply': s.add_argument('--only', nargs='*')
        if name == 'eval': s.add_argument('--split', choices=['train', 'test']); s.add_argument('--min', type=float, help='exit nonzero if any field scores below this (0-1)')
    a = ap.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
