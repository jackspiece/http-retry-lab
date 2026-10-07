"""Local HTTP experiment: decide what to do after an uncertain POST outcome."""
from dataclasses import dataclass, field
import http.client
import json
from urllib.parse import urlsplit


class InvalidReceipt(Exception):
    """The server replied, but the client cannot identify the completed write."""


@dataclass
class Outcome:
    state: str
    attempts: int
    ticket_id: str | None = None
    events: list[dict] = field(default_factory=list)


def post_once(url: str, payload: dict, key: str | None = None) -> tuple[int, bytes]:
    """Send one request to the experiment's loopback server; never follow redirects."""
    parsed = urlsplit(url)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.username or parsed.password:
        raise ValueError('This experiment uses http://127.0.0.1 only')
    body = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    headers = {'Content-Type': 'application/json', 'Connection': 'close'}
    if key:
        headers['Idempotency-Key'] = key
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=2)
    try:
        path = parsed.path or '/'
        if parsed.query:
            path += '?' + parsed.query
        connection.request('POST', path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read(65536)
    finally:
        connection.close()


def submit(url: str, payload: dict, *, provider_supports_keys: bool,
           key: str | None = None, max_attempts: int = 2) -> Outcome:
    """Retry an uncertain write only under the fixture's idempotency contract.

    The capability flag is an explicit assumption, not automatic discovery.
    Keep the same key and serialized payload for all attempts of one operation.
    """
    if not 1 <= max_attempts <= 5:
        raise ValueError('Use between one and five attempts in this local experiment')
    if provider_supports_keys and not key:
        raise ValueError('An idempotency contract needs an operation key')
    events = []
    for attempt in range(1, max_attempts + 1):
        try:
            status, body = post_once(url, payload, key)
            if 200 <= status < 300:
                try:
                    receipt = json.loads(body)
                except (ValueError, UnicodeError) as error:
                    raise InvalidReceipt('Response could not be decoded') from error
                if not isinstance(receipt, dict) or not isinstance(receipt.get('ticket_id'), str) or not receipt['ticket_id']:
                    raise InvalidReceipt('Response has no usable ticket receipt')
                events.append({'attempt': attempt, 'event': 'receipt_received', 'http_status': status})
                return Outcome('complete', attempt, receipt['ticket_id'], events)
            if 400 <= status < 500:
                # In this fixture, a 4xx response means the request was rejected
                # before a new record was written. This is a provider contract.
                events.append({'attempt': attempt, 'event': 'rejected', 'http_status': status})
                return Outcome('rejected', attempt, events=events)
            events.append({'attempt': attempt, 'event': 'outcome_uncertain', 'http_status': status})
            if 300 <= status < 400:
                return Outcome('review_required', attempt, events=events)
        except (OSError, http.client.HTTPException, InvalidReceipt) as error:
            events.append({'attempt': attempt, 'event': 'outcome_uncertain', 'error_type': type(error).__name__})
        if not provider_supports_keys or attempt == max_attempts:
            return Outcome('review_required', attempt, events=events)
    raise AssertionError('The attempt loop must return an outcome')
