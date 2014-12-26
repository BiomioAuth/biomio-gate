#!/usr/bin/env python

from ssl import SSLError
from websocket import create_connection, WebSocketTimeoutException, WebSocket

from biomio.protocol.message import BiomioMessageBuilder
from biomio.protocol.settings import settings
from biomio.protocol.crypt import Crypto

from nose.tools import ok_, eq_, nottest, raises
from nose.plugins.attrib import attr

import time
import logging
from hashlib import sha1
from os import urandom


ssl_options = {
    "ca_certs": "server.pem"
}


class BiomioTest:
    _registered_key = None
    _registered_user_id = None

    def __init__(self):
        self._ws = None
        self._builder = None
        self.last_server_message = None
        self.current_session_token = None
        self.session_refresh_token = None

    @nottest
    def new_connection(self, socket_timeout=5):
        # socket = WebSocket()
        socket = WebSocket(sslopt=ssl_options)
        # socket.connect("wss://gb.vakoms.com:{port}/websocket".format(port=settings.port))
        socket.connect("wss://{host}:{port}/websocket".format(host=settings.host, port=settings.port))
        socket.settimeout(socket_timeout)
        return socket

    @nottest
    def read_message(self, websocket):
        result = websocket.recv()
        response = BiomioMessageBuilder.create_message_from_json(result)
        self.last_server_message = response
        if response and not str(response.header.token) == self.current_session_token:
            self.set_session_token(str(response.header.token))
        if response and response.msg.oid == 'serverHello':
            self.session_refresh_token = str(response.msg.refreshToken)
        return response

    @nottest
    def send_message(self, message, websocket=None, close_connection=True, wait_for_response=True):

        if websocket is None:
            websocket = self.new_connection()

        websocket.send(message.serialize())

        response = None
        if wait_for_response:
            response = self.read_message(websocket=websocket)
            self.last_server_message = response

        if close_connection:
            websocket.close()

        return response

    @nottest
    def set_session_token(self, token):
        if self._builder:
            self._builder.set_header(token=token)
            self.current_session_token = token
        else:
            raise 'Run BiomioTest.setup_test() first to prepare for communication with server'

    @nottest
    def get_curr_connection(self):
        """Helper method to get current connected websocket.
           Should be used to get current websocket after some setup methods
          (e.g. setup_test_with_handshake) that creates connection with server
          and send messages to prepare test case.
        """
        if not self._ws:
            self._ws = self.new_connection()
        return self._ws

    @nottest
    def create_next_message(self, **kwargs):
        """Helper method to create next new client message.
        By default (if no parameters passed) it is initializes
        client message header with correct default values and correct next
        sequence number.
        """
        message = self._builder.create_message(**kwargs)
        return message

    @nottest
    def setup_test(self):
        """Default setup for test methods."""
        self._builder = BiomioMessageBuilder(oid='clientHeader', seq=0, protoVer='1.0', id='id', osId='os id',
                                             devId='devid', appId='app Id')
        self.last_server_message = None
        self.session_refresh_token = None
        self.current_session_token = None

    @nottest
    def teardown_test(self):
        """Default teardown for test methods"""
        if self._ws:
            if self._ws.connected:
                self._ws.close()
        self._ws = None
        self._builder = None
        self.last_server_message = None
        self.session_refresh_token = None
        self.current_session_token = None

    @nottest
    def setup_test_with_hello(self, secret=None, is_registration_required=True):
        self.setup_test()

        # Send hello message
        params = {
            'oid': 'clientHello'
        }

        if is_registration_required and not secret:
            self.check_app_registered()
            self._builder.set_header(id=BiomioTest._registered_user_id)
        elif secret:
            params['secret'] = secret

        message = self.create_next_message(**params)
        response = self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False)
        eq_(response.msg.oid, 'serverHello', msg='Response does not contains helloServer message')
        eq_(response.header.seq, int(message.header.seq) + 1,
            'Response sequence number is invalid (expected: %d, got: %d)' % (
                int(message.header.seq) + 1, response.header.seq))

    @nottest
    def setup_test_with_handshake(self, secret=None, is_registration_required=True):
        """Setup method for tests to perform handshake"""
        self.setup_test_with_hello(secret=secret, is_registration_required=is_registration_required)

        if secret:
            # Send ack message during registration
            message = self.create_next_message(oid='ack')
        else:
            digest = self.get_digest_for_next_message()
            message = self.create_next_message(oid='auth', key=digest)

        self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                          wait_for_response=False)

    @nottest
    def setup_with_session_restore(self, secret=None):
        """Performs handshake and closes connection without 'bye',
        so we could restore connection further"""
        # Perform handshake
        self.setup_test_with_handshake(secret=secret)

        # Close websocket on client side,
        # without sending bye message,
        # so we could restore session further
        websocket = self.get_curr_connection()
        websocket.close()

    @nottest
    def get_digest_for_next_message(self):
        header_str = self._builder.header_string()
        return Crypto.create_digest(data=header_str, key=BiomioTest._registered_key)

    @nottest
    def check_app_registered(self, id_to_create=None):
        if not self._registered_key or id_to_create is not None:
            self._builder.set_header(id=sha1(urandom(64)).hexdigest() if id_to_create is None else id_to_create)
            message = self.create_next_message(oid='clientHello', secret='secret')
            response = self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                                         wait_for_response=True)
            message = self.create_next_message(oid='ack')
            self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                              wait_for_response=False)
            message = self.create_next_message(oid='bye')
            self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                              wait_for_response=False)
            BiomioTest._registered_key = str(response.msg.key)
            BiomioTest._registered_user_id = str(message.header.id)

            self.teardown_test()
            self.setup_test()

    @nottest
    def setup_test_for_for_new_id(self):
        self.setup_test()
        self._builder.set_header(id=sha1(urandom(64)).hexdigest())


class TestTimeouts(BiomioTest):
    def setup(self):
        self.setup_test()

    def teardown(self):
        self.teardown_test()

    @attr('slow')
    def test_connection_timeout(self):
        websocket = self.new_connection(socket_timeout=60)
        response = self.read_message(websocket=websocket)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')

    @attr('slow')
    def test_connection_timer_restart(self):
        self.setup_test_with_handshake()

        message_timeout = 3  # Send a message every 3 seconds
        message_count = (settings.connection_timeout / message_timeout) + 1

        for i in range(message_count):
            time.sleep(message_timeout)
            connection = self.get_curr_connection()
            ok_(connection.connected, msg='Socket is not in connected state')
            message = self.create_next_message(oid='nop')
            self.send_message(websocket=connection, message=message, close_connection=False, wait_for_response=False)

        # Finish test, send bye message
        message = self.create_next_message(oid='bye')
        self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False)

    def test_session_ttl_not_zero(self):
        self.setup_test()
        message = self.create_next_message(oid='clientHello')
        response = self.send_message(message=message)
        ok_(not response.msg.ttl == 0, msg='Session TTL == 0')

    @attr('slow')
    def test_session_expire(self):

        message_timeout = settings.connection_timeout / 2  # Send a message every 3 seconds
        message_count = (settings.session_ttl / message_timeout) + 2

        # We will wait for message from server,
        # so we set timeout for blocking read socket operation to
        # message_timeout value (we will use that timeout
        # as a delay between messages)
        self.setup_test_with_handshake()

        expired = False
        for i in range(message_count):
            # Need to send nop messages to continue connection ttl,
            # but messages will be sent with the same session token, so
            # after a while session will be expired
            message = self.create_next_message(oid='nop')
            time.sleep(message_timeout)
            try:
                response = self.send_message(websocket=self.get_curr_connection(), message=message,
                                             close_connection=False, wait_for_response=True)
                if str(response.msg.oid) == 'bye':
                    expired = True
                    break
            except Exception, e:
                expired = True
                break

        ok_(expired, msg='Session does not expired %s' % self.current_session_token)


class TestRegistration(BiomioTest):
    def setup(self):
        self.setup_test()

    def teardown(self):
        self.teardown_test()

    def test_registration(self):
        self.setup_test_for_for_new_id()
        message = self.create_next_message(oid='clientHello', secret='secret')
        response = self.send_message(message=message)
        eq_(response.msg.oid, 'serverHello', msg='Response does not contains serverHello message')
        ok_(hasattr(response.msg, 'key') and response.msg.key, msg="Responce does not contains generated private key.")

    def test_ack_message(self):
        # Send ack message
        message = self.create_next_message(oid='clientHello', secret='secret')
        self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False)
        message = self.create_next_message(oid='ack')
        self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                          wait_for_response=False)

    @attr('slow')
    @raises(WebSocketTimeoutException, SSLError)
    def test_ack_message_response(self):
        self.setup_test_for_for_new_id()
        message = self.create_next_message(oid='clientHello', secret='secret')
        self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False)
        message = self.create_next_message(oid='ack')
        # Send message and wait for response,
        # server should not respond and close connection,
        # so WebsocketTimeoutException will be raised
        self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                          wait_for_response=True)


class TestConnectedState(BiomioTest):
    def setup(self):
        self.setup_test()

    def teardown(self):
        self.teardown_test()

    def test_hello_server(self):
        message = self.create_next_message(oid='clientHello')
        response = self.send_message(message=message)
        eq_(response.msg.oid, 'serverHello', msg='Response does not contains serverHello message')

    def test_invalid_message(self):
        websocket = self.new_connection()
        invalid_message_str = '{}'
        websocket.send(invalid_message_str)
        response = self.read_message(websocket=websocket)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')

    def test_invalid_json(self):
        websocket = self.new_connection()
        invalid_json_str = ''
        websocket.send(invalid_json_str)
        response = self.read_message(websocket=websocket)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')

    def test_invalid_sequence(self):
        message = self.create_next_message(oid='clientHello')
        message.header.seq = 1
        response = self.send_message(websocket=self.get_curr_connection(), message=message)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')
        pass

    def test_invalid_protocol_ver(self):
        message = self.create_next_message(oid='clientHello')
        message.header.protoVer = '2.0'
        response = self.send_message(websocket=self.get_curr_connection(), message=message)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')

    def test_nop_message_sent(self):
        message = self.create_next_message(oid='nop')
        response = self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')

    def test_token_generation(self):
        message = self.create_next_message(oid='clientHello')
        first_response = self.send_message(message=message, close_connection=True, websocket=self.new_connection())
        ok_(first_response.header.token, msg='Server returns empty token string')

        second_response = self.send_message(message=message, close_connection=True, websocket=self.new_connection())
        ok_(second_response.header.token, msg='Server returns empty token string')
        ok_(not str(first_response.header.token) == str(second_response.header.token),
            msg='Token string sould be unique for every connection')

    def test_refresh_token_generation(self):
        message = self.create_next_message(oid='clientHello')
        first_response = self.send_message(message=message, close_connection=True, websocket=self.new_connection())
        ok_(first_response.msg.refreshToken, msg='Server returns empty refresh token string')

        second_response = self.send_message(message=message, close_connection=True, websocket=self.new_connection())
        ok_(second_response.msg.refreshToken, msg='Server returns empty refresh token string')
        ok_(not str(first_response.msg.refreshToken) == str(second_response.msg.refreshToken),
            msg='Refresh token string sould be unique for every connection')

    @attr('slow')
    def test_session_restore(self):
        self.setup_with_session_restore()
        token = str(self.session_refresh_token)

        self.teardown_test()
        self.setup_test()

        self.set_session_token(token)
        message = self.create_next_message(oid='nop')
        try:
            self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                              wait_for_response=True)
        except (WebSocketTimeoutException, SSLError):
            pass

        time.sleep(settings.connection_timeout / 2)
        message = self.create_next_message(oid='bye')
        response = self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')

    def test_session_restore_error_with_invalid_token(self):
        self.setup_with_session_restore()

        self.teardown_test()
        self.setup_test()

        invalid_token = 'invalid_token_123'
        self.set_session_token(invalid_token)
        message = self.create_next_message(oid='nop')
        response = self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                                     wait_for_response=True)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')

    def test_inappropriate_regular_handshake(self):
        self.setup_with_session_restore()

        self.teardown_test()
        self.setup_test()

        invalid_id = sha1(urandom(64)).hexdigest()
        self._builder.set_header(id=invalid_id)
        message = self.create_next_message(oid='clientHello')
        response = self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                                     wait_for_response=True)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')

    def test_inappropriate_registration_handshake(self):
        self.setup_with_session_restore()

        self.teardown_test()
        self.setup_test()

        id_to_create = sha1(urandom(64)).hexdigest()
        self.check_app_registered(id_to_create)

        self._builder.set_header(id=id_to_create)

        message = self.create_next_message(oid='clientHello', secret='secret')
        response = self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                                     wait_for_response=True)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')


class TestHandshakeState(BiomioTest):
    def setup(self):
        self.setup_test_with_hello()

    def teardown(self):
        self.teardown_test()

    def test_invalid_message(self):
        websocket = self.get_curr_connection()
        invalid_message_str = '{}'
        websocket.send(invalid_message_str)
        response = self.read_message(websocket=websocket)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')

    def test_invalid_json(self):
        websocket = self.get_curr_connection()
        invalid_json_str = ''
        websocket.send(invalid_json_str)
        response = self.read_message(websocket=websocket)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')

    def test_invalid_sequence(self):
        message = self.create_next_message(oid='ack')
        message.header.seq = 1
        response = self.send_message(websocket=self.get_curr_connection(), message=message)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')
        pass

    def test_invalid_protocol_ver(self):
        message = self.create_next_message(oid='ack')
        message.header.protoVer = '2.0'
        response = self.send_message(websocket=self.get_curr_connection(), message=message)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')

    def test_any_other_message_received(self):
        message = self.create_next_message(oid='nop')
        response = self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status message')

    def test_auth_message(self):
        message = self.create_next_message(oid='auth', key=self.get_digest_for_next_message())
        websocket = self.get_curr_connection()
        self.send_message(websocket=websocket, message=message, wait_for_response=False, close_connection=False)

    @attr('slow')
    @raises(WebSocketTimeoutException, SSLError)
    def test_auth_message_response(self):
        message = self.create_next_message(oid='auth', key=self.get_digest_for_next_message())
        websocket = self.get_curr_connection()
        # Send message and wait for response,
        # server should not respond and close connection,
        # so WebsocketTimeoutException will be raised
        response = self.send_message(websocket=websocket, message=message, close_connection=False,
                                     wait_for_response=True)
        print response


class TestReadyState(BiomioTest):
    def setup(self):
        self.setup_test_with_handshake()

    def teardown(self):
        self.teardown_test()

    def test_nop_message(self):
        # Send nop message
        message = self.create_next_message(oid='nop')
        self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                          wait_for_response=False)

    def test_nop_message_response(self):
        message = self.create_next_message(oid='nop')
        # Send message and wait for response,
        # server should not respond and close connection,
        # so WebsocketTimeoutException will be raised
        response = self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                                     wait_for_response=True)
        eq_(response.msg.oid, 'nop', msg='Response does not contains nop message')

    def test_bye_message(self):
        # Send bye message
        message = self.create_next_message(oid='bye')
        response = self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')

    def test_invalid_sequence(self):
        message = self.create_next_message(oid='nop')
        message.header.seq = 1
        socket = self.get_curr_connection()
        response = self.send_message(websocket=socket, message=message, close_connection=False)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status message')

    def test_invalid_message(self):
        websocket = self.get_curr_connection()
        invalid_message_str = '{}'
        websocket.send(invalid_message_str)
        response = self.read_message(websocket=websocket)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')

    def test_invalid_json(self):
        websocket = self.get_curr_connection()
        invalid_json_str = ''
        websocket.send(invalid_json_str)
        response = self.read_message(websocket=websocket)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')

    def test_invalid_protocol_ver(self):
        message = self.create_next_message(oid='nop')
        message.header.protoVer = '2.0'
        response = self.send_message(websocket=self.get_curr_connection(), message=message)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        ok_(hasattr(response, 'status') and response.status, msg='Response does not contains status string')

    def test_message_sequence_with_bye(self):
        # Handshake done (setup method)
        # Send few nop's in a row
        message = self.create_next_message(oid='nop')
        self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                          wait_for_response=True)
        message = self.create_next_message(oid='nop')
        self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                          wait_for_response=True)
        message = self.create_next_message(oid='nop')
        self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False,
                          wait_for_response=True)

        # Send 'bye' and check sequence number
        message = self.create_next_message(oid='bye')
        response = self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False)
        eq_(response.msg.oid, 'bye', msg='Response does not contains bye message')
        eq_(response.header.seq, int(message.header.seq) + 1, msg='Bye response has invalid sequence number')

    @attr('slow')
    def test_session_refresh(self):
        message_timeout = settings.connection_timeout / 2
        message_count = (settings.session_ttl / message_timeout) - 1

        old_session_token = self.current_session_token

        expired = False
        for i in range(message_count):
            # Need to send nop messages to continue connection ttl,
            # but messages will be sent with the same session token, so
            # after a while session will be expired
            message = self.create_next_message(oid='nop')
            time.sleep(message_timeout)
            try:
                self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False)
            except Exception, e:
                expired = True
                break

        message = self.create_next_message(oid='nop')
        message.header.token = self.session_refresh_token
        self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False)

        for i in range(message_count):
            # Need to send nop messages to continue connection ttl,
            # but messages will be sent with the same session token, so
            # after a while session will be expired
            message = self.create_next_message(oid='nop')
            time.sleep(message_timeout)
            try:
                self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False)
            except Exception, e:
                expired = True
                break

        ok_(not expired, msg='Session expired instead of refresh')
        ok_(not old_session_token == self.current_session_token,
            msg='New session token not generated (old one present).')


class TestRpcCalls(BiomioTest):
    def setup(self):
        self.setup_test_with_handshake(is_registration_required=True)

    def teardown(self):
        self.teardown_test()

    def test_rpc_call(self):
        message = self.create_next_message(oid='rpcReq', namespace='extension_test_plugin', call='test_func', data={'keys': ['val1', 'val2'], 'values': ['1', '2']})
        response = self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False, wait_for_response=True)
        ok_(str(response.msg.oid) != 'bye', msg='Connection closed. Status: %s' % response.status)

    def test_rpc_ns_list(self):
        message = self.create_next_message(oid='rpcEnumNsReq')
        response = self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False, wait_for_response=True)
        ok_(str(response.msg.oid) != 'bye', msg='Connection closed. Status: %s' % response.status)

    def test_rpc_with_auth(self):
        message = self.create_next_message(oid='rpcReq', namespace='extension_test_plugin', call='test_funch_with_auth', data={'keys': ['val1', 'val2'], 'values': ['1', '2']})
        response = self.send_message(websocket=self.get_curr_connection(), message=message, close_connection=False, wait_for_response=True)
        ok_(str(response.msg.oid) != 'bye', msg='Connection closed. Status: %s' % response.status)

def main():
    pass

# Suppress logging in  python_jsonschema_objects module for bettter tests results readability
logger = logging.getLogger("python_jsonschema_objects.classbuilder")
logger.disabled = True
logger = logging.getLogger("python_jsonschema_objects")
logger.disabled = True


if __name__ == '__main__':
    main()
