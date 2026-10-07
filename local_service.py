"""A local ticket service with observable writes and controlled response faults."""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading


class LocalService:
    def __init__(self, *, supports_keys: bool, faults: tuple[str, ...] = ()):
        self.supports_keys = supports_keys
        self.faults = faults
        self.records = []
        self.requests = []
        self.cache = {}
        self.lock = threading.Lock()

    def dispatch(self, payload: dict, key: str | None) -> tuple[str, int, bytes]:
        canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)
        with self.lock:
            number = len(self.requests) + 1
            event = {'request': number, 'key': key, 'write': False, 'cache_hit': False}
            self.requests.append(event)
            if self.supports_keys and key and key in self.cache:
                old_payload, receipt = self.cache[key]
                if old_payload != canonical:
                    event['result'] = 'key_payload_conflict'
                    return 'reply', 409, b'{"error":"key already belongs to another payload"}'
                event['cache_hit'] = True
                event['result'] = 'cached_receipt'
                return 'reply', 200, json.dumps(receipt).encode()
            fault = self.faults[number - 1] if number <= len(self.faults) else 'none'
            if fault == 'unavailable_before_write':
                event['result'] = 'unavailable_before_write'
                return 'reply', 503, b'{"error":"temporarily unavailable"}'
            if fault == 'reject':
                event['result'] = 'validation_rejected'
                return 'reply', 422, b'{"error":"invalid ticket"}'
            if fault == 'redirect':
                event['result'] = 'redirect_response'
                return 'redirect', 307, b'{}'
            receipt = {'ticket_id': f'ticket-{len(self.records) + 1}'}
            self.records.append({'ticket_id': receipt['ticket_id'], 'payload': copy.deepcopy(payload)})
            event['write'] = True
            if self.supports_keys and key:
                self.cache[key] = (canonical, receipt)
            if fault == 'drop_after_write':
                event['result'] = 'written_then_connection_closed'
                return 'drop', 0, b''
            if fault == 'invalid_json_after_write':
                event['result'] = 'written_then_invalid_json'
                return 'reply', 201, b'{broken'
            event['result'] = 'written_then_receipt_sent'
            return 'reply', 201, json.dumps(receipt).encode()

    def snapshot(self) -> dict:
        with self.lock:
            return copy.deepcopy({'records': self.records, 'requests': self.requests})

    def __enter__(self):
        service = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):
                pass

            def do_POST(self):
                if self.path != '/tickets':
                    self.send_error(404)
                    return
                size = int(self.headers.get('Content-Length', 0))
                payload = json.loads(self.rfile.read(size))
                action, status, body = service.dispatch(payload, self.headers.get('Idempotency-Key'))
                if action == 'drop':
                    # The write has already happened. Drop the real TCP response.
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    self.connection.close()
                    return
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Connection', 'close')
                if action == 'redirect':
                    self.send_header('Location', '/not-an-automatic-retry')
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.url = f'http://127.0.0.1:{self.server.server_port}/tickets'
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError('The experiment server did not stop')
