"""Deterministic personal briefing from existing Apollo records, never model guesses."""
from datetime import datetime, timedelta

FAVORITE_ARTISTS = ['Jeff Buckley', 'Frank Ocean', 'Sade', 'Portishead', 'The Smiths', 'The Marías', 'Daniel Caesar', 'Brent Faiyaz', 'PartyNextDoor', 'Bryson Tiller', 'Steve Lacy', 'TV Girl', 'Mac DeMarco', 'Berlioz', 'Dublon']


def parse_time(value, zone):
    if isinstance(value, dict): value = value.get('dateTime') or value.get('date')
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.astimezone(zone) if parsed.tzinfo else parsed.replace(tzinfo=zone)
    except (ValueError, TypeError): return None


def personal_brief(now, events, tasks, health, calendar_errors=None, tasks_available=True):
    today, insights, notices = [], [], []
    connections = {item['id']: item for item in health.get('integrations', [])}
    for identifier, label in [('google_calendar', 'Google Calendar'), ('canvas_calendar', 'Canvas')]:
        item = connections.get(identifier, {})
        status = item.get('status', 'unknown')
        if status != 'connected':
            notices.append({'source': label, 'message': f'{label}: ' + (
                'reconnect to restore current information.' if item.get('needs_attention') else
                'not connected; information is unavailable.' if status in {'not_configured', 'disconnected'} else
                'current information could not be confirmed. Cached records may be stale.'),
                'action': 'connections'})
    if calendar_errors:
        notices.append({'source': 'Calendar', 'message': 'Some calendar data could not be refreshed; this schedule may be incomplete.', 'action': 'connections'})
    if not tasks_available:
        notices.append({'source': 'Tasks', 'message': 'Tasks could not be loaded. Deadlines are unavailable.'})

    scheduled = []
    for event in events:
        start = parse_time(event.get('start'), now.tzinfo)
        end = parse_time(event.get('end'), now.tzinfo) or start
        if not start or not end: continue
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if start < day_start + timedelta(days=1) and end > day_start:
            scheduled.append((start, end, event))
    scheduled.sort(key=lambda row: row[0])
    if scheduled:
        lines = []
        for start, end, event in scheduled:
            all_day = 'date' in (event.get('start') or {})
            when = 'All day' if all_day else start.strftime('%H:%M') + '–' + end.strftime('%H:%M')
            lines.append(f"{when} · {event.get('summary') or 'Untitled event'}" + (f" · {event['location']}" if event.get('location') else ''))
        today.append({'category': 'My day', 'headline': f'{len(scheduled)} calendar commitments today',
                      'body': ' · '.join(lines[:3]), 'details': '\n'.join(lines), 'source': 'Connected calendar'})
        conflicts = []
        for index, (start, end, event) in enumerate(scheduled):
            if 'date' in (event.get('start') or {}): continue
            for other_start, other_end, other in scheduled[index + 1:]:
                if 'date' not in (other.get('start') or {}) and max(start, other_start) < min(end, other_end):
                    conflicts.append(f"{event.get('summary', 'Event')} overlaps {other.get('summary', 'event')} at {other_start:%H:%M}.")
        if conflicts:
            insights.append({'category': 'Personal intelligence', 'headline': 'Scheduling conflicts to resolve',
                             'body': conflicts[0], 'details': '\n'.join(conflicts), 'source': 'Connected calendar'})
        elif len(scheduled) >= 5:
            insights.append({'category': 'Personal intelligence', 'headline': 'A busy day ahead',
                             'body': f'{len(scheduled)} commitments are on your calendar. Check locations and preparation before your first appointment.', 'source': 'Connected calendar'})
    elif connections.get('google_calendar', {}).get('status') == 'connected' and not calendar_errors:
        today.append({'category': 'My day', 'headline': 'No calendar commitments today', 'body': 'Your connected calendar has no events today.', 'source': 'Connected calendar'})

    due = []
    for task in tasks:
        if task.get('completed'): continue
        deadline = parse_time(task.get('due_at'), now.tzinfo)
        if deadline and deadline.date() <= (now + timedelta(days=7)).date():
            # Date-only deadlines are due through the end of the stated day.
            overdue = deadline.date() < now.date() if len(str(task.get('due_at'))) == 10 else deadline < now
            due.append((deadline, overdue, task))
    due.sort(key=lambda row: row[0])
    if due:
        def line(row):
            deadline, overdue, task = row
            label = 'Overdue' if overdue else 'Due today' if deadline.date() == now.date() else f'Due {deadline:%a %d %b}'
            return f"{label} · {task['title']} ({task.get('due_at')})"
        today.append({'category': 'My day', 'headline': f'{len(due)} unfinished deadlines to review',
                      'body': ' · '.join(line(row) for row in due[:3]), 'details': '\n'.join(line(row) for row in due),
                      'source': 'Apollo tasks and Canvas'})
        overdue = [row for row in due if row[1]]
        if overdue:
            insights.append({'category': 'Personal intelligence', 'headline': f'{len(overdue)} overdue priorities',
                             'body': f"Start by reviewing “{overdue[0][2]['title']}”. Its saved deadline has passed and it is still unfinished.", 'source': 'Saved task status'})
    elif tasks_available:
        today.append({'category': 'My day', 'headline': 'No approaching task deadlines recorded',
                      'body': 'No unfinished saved tasks are due in the next seven days. Tasks without dates may still need attention.', 'source': 'Apollo tasks'})
    return {'my_day': today, 'personal_intelligence': insights, 'availability': notices}


def whoop_observation(summary, now):
    """Only summarize scored, matching overnight records from today."""
    sleep, recovery = summary.get('sleep') or {}, summary.get('recovery') or {}
    ended = parse_time(sleep.get('end'), now.tzinfo)
    if (not ended or ended.date() != now.date() or sleep.get('nap') or
            not sleep.get('id') or str(sleep['id']) != str(recovery.get('sleep_id')) or
            sleep.get('score_state') != 'SCORED' or recovery.get('score_state') != 'SCORED'):
        return None
    hours, score = sleep.get('total_sleep_hours'), recovery.get('score')
    if not isinstance(hours, (int, float)) or not isinstance(score, (int, float)): return None
    return {'category': 'Personal intelligence', 'headline': 'Your latest overnight measurements',
            'body': f'WHOOP recorded {hours:g} hours of sleep and a recovery score of {score:g}% for the sleep ending today.',
            'source': 'Connected WHOOP records', 'published_at': sleep.get('end')}
