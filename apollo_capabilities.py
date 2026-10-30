"""Bounded, code-checked descriptions of Apollo's implemented surfaces.

This registry is about supported operations, never proof that an external
account is connected. The latter must come from its real connection adapter.
"""
import json
import re
from functools import lru_cache
from pathlib import Path


# Keep each entry bound to a real backend callable or existing handler route.
# The registry refuses to advertise an operation when its implementation is
# absent from the current server revision.
CAPABILITIES = (
    ('chat', 'Chat', 'Ask questions, research and use saved conversations',
     ('answer', 'search history', 'generate image'), ('/api/chats', '/api/memory'),
     ('do_GET', 'do_POST'), 'chat', 'Private Chat and History may require identity verification'),
    ('music', 'Music', 'Spotify playback and listening insights',
     ('playback', 'insights', 'recaps'), ('/api/music/analytics', '/api/spotify/search'),
     ('apollo_spotify_tool_command',), 'music', 'Spotify connection required for live playback'),
    ('calendar', 'Calendar', 'Google Calendar events and planning',
     ('read events', 'create event'), ('/api/calendar/events',),
     ('apollo_calendar_events',), 'calendar', 'Google connection required for live events'),
    ('canvas', 'Canvas', 'Canvas assignments synchronized into Tasks',
     ('read assignments',), ('/api/calendar/subscriptions/canvas/status',),
     ('calendar_subscription_status',), 'calendar', 'Canvas subscription required'),
    ('whoop', 'WHOOP', 'Recovery, sleep and strain summaries',
     ('read recovery',), ('/api/whoop/summary',),
     ('whoop_connection_status',), 'whoop', 'WHOOP connection required'),
    ('tasks', 'Tasks', 'Personal tasks and due dates',
     ('read tasks', 'update task'), ('/api/tasks',),
     ('get_tasks',), 'tasks', None),
    ('routines', 'Routines', 'Recurring personal routines',
     ('read routines', 'update routine'), ('/api/routines',),
     ('do_GET', 'do_POST'), 'routines', None),
    ('studio', 'Studio', 'Music production workspace',
     ('open workspace',), ('/api/studio/projects',),
     ('do_GET',), 'studio', None),
    ('debrief', 'Daily Debrief', 'Daily summary from connected sources',
     ('read briefing',), ('/api/debrief',),
     ('do_GET',), 'debrief', 'Some sources may be disconnected'),
    ('gmail', 'Gmail', 'Search and read email; send only after confirmation',
     ('search mail', 'read mail', 'draft reply', 'confirm send'), ('/api/gmail/status',),
     ('do_GET', 'do_POST'), 'connections', 'Gmail authorization required'),
    ('settings', 'Settings', 'Appearance, connections, memory and security controls',
     ('open settings', 'review connections', 'review memory'), ('/api/security/state',),
     ('do_GET',), 'settings', 'Protected settings may require verification'),
)
VIEWS = {'home', 'apollo', 'music', 'calendar', 'tasks', 'studio', 'settings'}
PANELS = {'history', 'music-insights', 'security', 'connections', 'memory'}
APP_QUERY = re.compile(
    r'\b(?:apollo|this app|this (?:page|screen|chart|setting|panel)|'
    r'what (?:can you|does this)|where (?:can i|do i)|'
    r'(?:my|this) (?:spotify|music|calendar|canvas|whoop|email|gmail)|'
    r'(?:open|close|show|switch to|go to) (?:the |my )?'
    r'(?:music|calendar|tasks|studio|settings|history|university))\b',
    re.I,
)
ALIASES = {
    'spotify': 'music', 'insights': 'music', 'canvas': 'canvas',
    'email': 'gmail', 'mail': 'gmail', 'university': None,
}


@lru_cache(maxsize=2)
def _implemented_routes(source_path):
    try:
        return Path(source_path).read_text(encoding='utf-8')
    except OSError:
        return ''


def registry(server):
    implementation = '\n'.join(
        _implemented_routes(str(getattr(module, '__file__', '')))
        for module in (server, getattr(server, 'apollo_security', None),
                       getattr(server, 'apollo_intelligence', None))
    )
    result = []
    for ident, name, description, operations, endpoints, handlers, permission, limitation in CAPABILITIES:
        if not all(hasattr(server, handler) or hasattr(server.ApolloHandler, handler) for handler in handlers):
            continue
        if not all(endpoint in implementation for endpoint in endpoints):
            continue
        result.append({
            'id': ident, 'name': name, 'description': description,
            'operations': list(operations), 'endpoints': list(endpoints),
            'permission': permission, 'enabled': True,
            'availability': 'requires_connection' if limitation and 'connection required' in limitation.lower() else 'registered',
            'limitation': limitation,
        })
    return result


def ui_state(client_context):
    supplied = client_context.get('ui_state') if isinstance(client_context, dict) else None
    if not isinstance(supplied, dict):
        return {}
    view = str(supplied.get('view') or '').lower()
    panel = str(supplied.get('panel') or '').lower()
    state = {}
    if view in VIEWS:
        state['view'] = view
    if panel in PANELS:
        state['panel'] = panel
    if state.get('view') == 'music':
        section = str(supplied.get('music_section') or '')
        period = str(supplied.get('music_period') or '')
        anchor = str(supplied.get('music_anchor') or '')
        if section in {'player', 'insights', 'recaps'}:
            state['music_section'] = section
        if period in {'daily', 'weekly', 'monthly', 'yearly', 'lifetime'}:
            state['music_period'] = period
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', anchor):
            state['music_anchor'] = anchor
    # A UI snapshot is a navigation hint, not evidence about private data.
    return state


def context_for_query(server, question, client_context=None):
    question = str(question or '')[:500]
    state = ui_state(client_context)
    if not APP_QUERY.search(question):
        return None
    entries = registry(server)
    tokens = set(re.findall(r'[a-z]+', question.lower()))
    tokens.update(ALIASES[token] for token in list(tokens) if token in ALIASES and ALIASES[token])
    selected = [item for item in entries if item['id'] in tokens
                or item['name'].lower() in question.lower()]
    if not selected and state.get('view'):
        selected = [item for item in entries if item['id'] == state['view']]
    if not selected:
        selected = entries if re.search(r'\b(?:apollo|this app|can you)\b', question, re.I) else []
    unsupported = 'university' if 'university' in tokens and not any(
        item['id'] == 'university' for item in entries
    ) else None
    payload = {'capabilities': selected[:11], 'ui_state': state}
    if unsupported:
        payload['unregistered_feature'] = unsupported
    return json.dumps(payload, ensure_ascii=False, separators=(',', ':'))[:5500] if selected or state or unsupported else None
