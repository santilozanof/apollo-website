"""Persist safe health snapshots; outages cannot erase a confirmed auth problem."""
import json
import threading
import time
from datetime import datetime, timezone

ATTENTION = {'reconnection_required', 'expired_authorization', 'invalid_credentials'}


def merge_snapshot(current, previous):
    old = {item['id']: item for item in previous.get('integrations', [])}
    for item in current.get('integrations', []):
        prior = old.get(item['id'], {})
        status = item.get('status')
        # An absent account is not a broken connection unless we knew it worked.
        if status == 'disconnected':
            status = 'reconnection_required' if prior.get('ever_connected') or prior.get('needs_attention') else 'not_configured'
        if status == 'temporary_error' and prior.get('needs_attention'):
            item['last_check_status'] = status
            status = prior['status']
        item['status'] = status
        item['needs_attention'] = status in ATTENTION
        item['ever_connected'] = bool(prior.get('ever_connected') or item.get('connected'))
    current['checked_at'] = datetime.now(timezone.utc).isoformat()
    return current


class HealthMonitor:
    def __init__(self, read, write, probe, ttl=120):
        self.read, self.write, self.probe, self.ttl = read, write, probe, ttl
        self.lock = threading.Lock()
        self.at = 0
        self.value = None

    def snapshot(self, force=False, wait=False):
        if self.value is None:
            try: self.value = json.loads(self.read() or '{}')
            except (ValueError, TypeError): self.value = {}
        due = self.at == 0 or time.monotonic() - self.at >= (10 if force else self.ttl)
        if due and self.lock.acquire(blocking=False):
            if wait:
                self._refresh()
            else:
                threading.Thread(target=self._refresh, daemon=True, name='apollo-connection-health').start()
        elif wait and self.lock.locked():
            # A chat lookup must not mistake an in-progress first probe for
            # an empty connected-account list. UI polling can stay asynchronous.
            if self.lock.acquire(timeout=30):
                self.lock.release()
        if not self.value or 'integrations' not in self.value:
            return {'integrations': [], 'status': 'processing' if self.lock.locked() else 'unavailable'}
        return dict(self.value)

    def _refresh(self):
        try:
            value = merge_snapshot(self.probe(), self.value or {})
            self.write(json.dumps(value))
            self.value = value
        except Exception:
            pass  # No claim about authorization on an inconclusive check.
        finally:
            self.at = time.monotonic()
            self.lock.release()
