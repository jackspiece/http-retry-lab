import http.client
import json
import unittest

from local_service import LocalService
from retry_client import post_once, submit

TICKET = {'subject': 'Move the workshop booking', 'request_id': 'demo-001'}


class RetryOutcomes(unittest.TestCase):
    def test_lost_response_can_hide_a_successful_write(self):
        with LocalService(supports_keys=False, faults=('drop_after_write',)) as service:
            result = submit(service.url, TICKET, provider_supports_keys=False)
            self.assertEqual((result.state, result.attempts, result.ticket_id), ('review_required', 1, None))
            self.assertEqual(len(service.snapshot()['records']), 1)

    def test_blind_retry_creates_two_records(self):
        with LocalService(supports_keys=False, faults=('drop_after_write',)) as service:
            with self.assertRaises((OSError, http.client.HTTPException)):
                post_once(service.url, TICKET)
            status, body = post_once(service.url, TICKET)
            self.assertEqual((status, json.loads(body)['ticket_id']), (201, 'ticket-2'))
            self.assertEqual(len(service.snapshot()['records']), 2)

    def test_same_key_recovers_the_original_receipt_after_lost_response(self):
        with LocalService(supports_keys=True, faults=('drop_after_write',)) as service:
            result = submit(service.url, TICKET, provider_supports_keys=True, key='stable-operation')
            state = service.snapshot()
            self.assertEqual((result.state, result.attempts, result.ticket_id), ('complete', 2, 'ticket-1'))
            self.assertEqual(len(state['records']), 1)
            self.assertTrue(state['requests'][1]['cache_hit'])
            self.assertEqual({r['key'] for r in state['requests']}, {'stable-operation'})

    def test_a_header_does_not_make_an_unsupported_service_idempotent(self):
        with LocalService(supports_keys=False, faults=('drop_after_write',)) as service:
            result = submit(service.url, TICKET, provider_supports_keys=True, key='ignored-key')
            self.assertEqual(result.ticket_id, 'ticket-2')
            self.assertEqual(len(service.snapshot()['records']), 2)

    def test_reusing_key_for_a_different_payload_is_rejected(self):
        with LocalService(supports_keys=True) as service:
            first = submit(service.url, TICKET, provider_supports_keys=True, key='operation')
            second = submit(service.url, {'subject': 'Different request'}, provider_supports_keys=True, key='operation')
            self.assertEqual(first.state, 'complete')
            self.assertEqual(second.state, 'rejected')
            self.assertEqual(second.events[0]['http_status'], 409)
            self.assertEqual(len(service.snapshot()['records']), 1)

    def test_the_same_operation_can_be_replayed_in_another_client_call(self):
        with LocalService(supports_keys=True) as service:
            first = submit(service.url, TICKET, provider_supports_keys=True, key='saved-operation')
            second = submit(service.url, dict(reversed(list(TICKET.items()))), provider_supports_keys=True, key='saved-operation')
            self.assertEqual(first.ticket_id, second.ticket_id)
            self.assertEqual(len(service.snapshot()['records']), 1)

    def test_invalid_receipt_after_write_uses_same_key_for_recovery(self):
        with LocalService(supports_keys=True, faults=('invalid_json_after_write',)) as service:
            result = submit(service.url, TICKET, provider_supports_keys=True, key='operation')
            self.assertEqual((result.state, result.attempts, result.ticket_id), ('complete', 2, 'ticket-1'))
            self.assertEqual(len(service.snapshot()['records']), 1)

    def test_retry_budget_stops_an_unavailable_provider(self):
        with LocalService(supports_keys=True, faults=('unavailable_before_write',) * 4) as service:
            result = submit(service.url, TICKET, provider_supports_keys=True, key='operation', max_attempts=3)
            state = service.snapshot()
            self.assertEqual((result.state, result.attempts), ('review_required', 3))
            self.assertEqual((len(state['requests']), len(state['records'])), (3, 0))

    def test_a_503_is_not_blindly_retried_without_provider_support(self):
        with LocalService(supports_keys=False, faults=('unavailable_before_write',)) as service:
            result = submit(service.url, TICKET, provider_supports_keys=False)
            self.assertEqual((result.state, result.attempts), ('review_required', 1))
            self.assertEqual(len(service.snapshot()['requests']), 1)

    def test_validation_rejection_is_not_retried(self):
        with LocalService(supports_keys=True, faults=('reject',)) as service:
            result = submit(service.url, TICKET, provider_supports_keys=True, key='operation')
            self.assertEqual((result.state, result.attempts), ('rejected', 1))
            self.assertEqual(len(service.snapshot()['records']), 0)

    def test_redirect_is_not_followed(self):
        with LocalService(supports_keys=True, faults=('redirect',)) as service:
            result = submit(service.url, TICKET, provider_supports_keys=True, key='operation')
            self.assertEqual((result.state, result.attempts), ('review_required', 1))
            self.assertEqual(len(service.snapshot()['requests']), 1)

    def test_invalid_payload_fails_before_any_request(self):
        with LocalService(supports_keys=True) as service:
            with self.assertRaises(ValueError):
                submit(service.url, {'value': float('nan')}, provider_supports_keys=True, key='operation')
            self.assertEqual(len(service.snapshot()['requests']), 0)

    def test_external_destination_is_rejected_before_any_request(self):
        with LocalService(supports_keys=True) as service:
            with self.assertRaises(ValueError):
                submit(service.url.replace('127.0.0.1', 'example.com'), TICKET, provider_supports_keys=True, key='operation')
            self.assertEqual(len(service.snapshot()['requests']), 0)


if __name__ == '__main__':
    unittest.main()
