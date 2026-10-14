import os
import unittest
from unittest.mock import patch
from broker import Broker, process_identity
from core import ApprovalError
from gi.repository import GLib


class Invocation:
    def __init__(self):
        self.result = None
        self.denial = None

    def return_value(self, value):
        self.result = value.unpack()[0]

    def return_dbus_error(self, _name, reason):
        self.denial = reason


class AuthorityTransport:
    def __init__(self, authorized):
        self.authorized = authorized
        self.callback = None

    def call(self, destination, path, interface, method, parameters, result_type, flags, timeout, cancellable, callback, data):
        if method == 'CheckAuthorization':
            # Exercise the actual GVariant encoding and ensure the exact scope reaches the authority.
            self.parameters = parameters.unpack()
            self.callback = callback

    def call_finish(self, _result):
        return GLib.Variant('((bba{ss}))', ((self.authorized, False, {}),))

    def finish(self):
        self.callback(self, object(), None)


class BrokerTests(unittest.TestCase):
    def setUp(self):
        logging = patch('broker.syslog.syslog')
        logging.start()
        self.addCleanup(logging.stop)
        self.uid = os.getuid()
        self.actor = (os.getpid(), process_identity(os.getpid())[2])
        self.broker = Broker(self.uid)
        self.broker._actor = lambda sender, pid: (self.uid, self.actor)
        self.request = {'session': 'session-1', 'cwd': '/home/q/project', 'action': 'Publish this change', 'exceptions': ['Skip local checks for this change']}

    def authenticate(self, authorized):
        self.transport = AuthorityTransport(authorized)
        self.broker.bus = self.transport
        self.invocation = Invocation()
        self.broker._request(':1.123', self.actor[0], self.uid, self.actor, self.request, self.invocation)

    def test_denial_creates_no_capability_and_releases_the_pending_request(self):
        self.authenticate(False)
        self.transport.finish()
        self.assertIsNotNone(self.invocation.denial)
        self.assertIsNone(self.invocation.result)
        self.assertEqual(self.broker.store.count(), 0)
        self.assertIsNone(self.broker.pending)

    def test_authority_receives_frozen_exact_action_and_exceptions(self):
        self.authenticate(True)
        displayed = self.transport.parameters[2]['polkit.message']
        self.assertIn('Publish this change', displayed)
        self.assertIn('Skip local checks for this change', displayed)
        self.request['action'] = 'Delete unrelated work'
        self.transport.finish()
        self.assertEqual(self.broker.store.count(), 1)
        grant = next(iter(self.broker.store.grants.values()))
        self.assertEqual(grant['request']['action'], 'Publish this change')

    def test_caller_disconnection_cancels_even_a_late_positive_authority_reply(self):
        self.authenticate(True)
        self.broker.owner_changed(None, None, None, None, None, GLib.Variant('(sss)', (':1.123', ':1.123', '')))
        self.transport.finish()
        self.assertEqual(self.broker.store.count(), 0)
        self.assertIsNotNone(self.invocation.denial)

    def test_process_replacement_during_password_entry_cannot_receive_a_capability(self):
        self.authenticate(True)
        self.broker._actor = lambda sender, pid: (self.uid, (self.actor[0], self.actor[1] + 1))
        self.transport.finish()
        self.assertEqual(self.broker.store.count(), 0)
        self.assertIsNotNone(self.invocation.denial)

    def test_unrelated_process_cannot_claim_the_requesting_agent_identity(self):
        broker = Broker(self.uid)
        broker._dbus_property = lambda sender, method: self.uid if method == 'GetConnectionUnixUser' else os.getpid()
        _, actual = broker._actor(':1.123', os.getpid())
        self.assertEqual(actual, self.actor)
        with self.assertRaises(ApprovalError):
            broker._actor(':1.123', 1)


if __name__ == '__main__':
    unittest.main()
