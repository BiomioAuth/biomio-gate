from itertools import izip
from functools import wraps
import logging
from os import urandom
from hashlib import sha1

from jsonschema import ValidationError
import tornado.gen
import greenado
from biomio.constants import REDiS_TRAINING_RETRIES_COUNT_KEY, REDIS_VERIFICATION_RETIES_COUNT_KEY, \
    HYBRID_APP_TYPE_PREFIX
from biomio.constants import PROBE_APP_TYPE_PREFIX
from biomio.protocol.data_stores.condition_data_store import ConditionDataStore
from biomio.protocol.data_stores.device_information_store import DeviceInformationStore
from biomio.protocol.data_stores.device_resources_store import DeviceResourcesDataStore

from biomio.protocol.message import BiomioMessageBuilder
from biomio.protocol.probes.policy_engine.policy_engine_manager import PolicyEngineManager
from biomio.protocol.storage.redis_storage import RedisStorage
from biomio.third_party.fysom import Fysom, FysomError
from biomio.protocol.sessionmanager import SessionManager
from biomio.protocol.settings import settings
from biomio.protocol.crypt import Crypto
from biomio.protocol.rpc.rpc_handler import RpcHandler
from biomio.protocol.data_stores.application_data_store import ApplicationDataStore
from biomio.protocol.probes.policymanager import PolicyManager
from biomio.protocol.probes.policies.fixedorderpolicy import FIELD_AUTH_TYPE, FIELD_SAMPLES_NUM
from biomio.protocol.rpc.bioauthflow import BioauthFlow, STATE_AUTH_TRAINING_STARTED
from biomio.protocol.probes.proberequest import ProbeRequest
from biomio.tries_simulator.tries_simulator_manager import TriesSimulatorManager

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = '1.0'

# States
STATE_CONNECTED = 'connected'
STATE_HANDSHAKE = 'handshake'
STATE_REGISTRATION = 'registration'
STATE_GETTING_RESOURCES = 'resourceget'
STATE_APP_REGISTERED = 'appregistered'
STATE_READY = 'ready'
STATE_DISCONNECTED = 'disconnected'
STATE_PROBE_TRYING = 'probetrying'
STATE_GETTING_PROBES = 'probegetting'


def _is_header_valid(e):
    """Helper method to verify header.
    Returns true if header information is valid, false otherwise
    Method attaches status attribute to the event parameter passed.
    Status contains error string in case when validation fails."""

    is_valid = True
    if not e.protocol_instance.is_sequence_valid(e.request.header.seq):
        is_valid = False
        e.status = 'Message sequence number is invalid'

    if not e.protocol_instance.is_protocol_version_valid(e.request.header.protoVer):
        is_valid = False
        e.status = 'Protocol version is invalid'

    return is_valid


def verify_header(verify_func):
    """
    Decorator that performs message header verification.
    :param verify_func: Callbacks used to make decision about next protocol state.
     Should take single parameter e - state event object.
    """

    def _decorator(e, *args, **kwargs):
        if not _is_header_valid(e, *args, **kwargs):
            return STATE_DISCONNECTED
        return verify_func(e, *args, **kwargs)

    return wraps(verify_func)(_decorator)


@greenado.generator
def get_app_data_helper(app_id, key=None):
    value = None
    try:
        app_data = yield tornado.gen.Task(ApplicationDataStore.instance().get_data, app_id)

        if not app_data:
            app_data = {}

        if key is not None:
            app_data = app_data.get(key, None)

    except Exception as e:
        logger.exception(e)

    raise tornado.gen.Return(value=app_data)


@greenado.generator
def get_app_keys_helper(app_id, extension=False):
    value = None
    try:
        if extension:
            app_data = yield tornado.gen.Task(ApplicationDataStore.instance().get_probe_ids_by_user_email, app_id)
        else:
            app_data = yield tornado.gen.Task(ApplicationDataStore.instance().get_extension_ids_by_probe_id, app_id)

        value = app_data if app_data is not None else {}
    except Exception as e:
        logger.exception(e)
    raise tornado.gen.Return(value=value)


class MessageHandler:
    @staticmethod
    @verify_header
    def on_client_hello_message(e):
        # "hello" should be received in connected state
        # and message does not contain refresh token
        if e.src == STATE_CONNECTED:
            if not hasattr(e.request.header, "token") \
                    or not e.request.header.token:

                # Create new session
                # TODO: move to some state handling callback
                e.protocol_instance.start_new_session()

                if hasattr(e.request.msg, "secret") \
                        and e.request.msg.secret:
                    if not hasattr(e.request.header, "appId") \
                            or not e.request.header.appId:
                        return STATE_REGISTRATION
                    else:
                        e.status = "Application id is set during registration handshake."
                else:
                    if hasattr(e.request.header, "appId") \
                            and e.request.header.appId:
                        fingerprint = str(e.request.header.appId)
                        app_data = get_app_data_helper(app_id=fingerprint)
                        pub_key = app_data.get('public_key') if app_data is not None else None
                        if pub_key is None:
                            e.status = "Regular handshake is inappropriate. It is required to run registration handshake first."
                            return STATE_DISCONNECTED
                        if str(e.request.header.appType) == 'probe':
                            e.protocol_instance.app_users = app_data.get('users')
                        real_fingerprint = Crypto.get_public_rsa_fingerprint(pub_key)
                        logger.debug("PUBLIC KEY: %s" % pub_key)
                        logger.debug("FINGERPRINT: %s" % real_fingerprint)
                        if pub_key and real_fingerprint == fingerprint:
                            if pub_key is not None:
                                return STATE_HANDSHAKE
                            e.status = "Regular handshake is inappropriate. It is required to run registration handshake first."
                        else:
                            e.status = "Regular handshake failed. Invalid fingerprint."

        return STATE_DISCONNECTED

    @staticmethod
    @verify_header
    def on_ack_message(e):
        if (str(e.request.header.appType) == 'extension'):
            return STATE_READY
        app_id = str(e.request.header.appId)
        existing_resources = DeviceResourcesDataStore.instance().get_data(device_id=app_id)
        if existing_resources is not None:
            e.protocol_instance.available_resources = existing_resources
            return STATE_READY
        return STATE_GETTING_RESOURCES

    @staticmethod
    @verify_header
    def on_nop_message(e):
        if e.src == STATE_READY \
                or e.src == STATE_PROBE_TRYING \
                or e.src == STATE_GETTING_PROBES or e.src == STATE_GETTING_RESOURCES:
            message = e.protocol_instance.create_next_message(
                request_seq=e.request.header.seq,
                oid='nop'
            )
            e.protocol_instance.send_message(responce=message)
            return e.src

        return STATE_DISCONNECTED

    @staticmethod
    def on_bye_message(e):
        return STATE_DISCONNECTED

    @staticmethod
    @verify_header
    def on_auth_message(e):
        app_id = str(e.request.header.appId)
        app_data = get_app_data_helper(app_id=app_id)
        key = app_data.get('public_key')
        header_str = BiomioMessageBuilder.header_from_message(e.request)

        if Crypto.check_digest(key=key, data=header_str, digest=str(e.request.msg.key)):
            protocol_connection_established(protocol_instance=e.protocol_instance, app_id=app_id)
            if str(e.request.header.appType) == 'extension':
                return STATE_READY
            e.protocol_instance.app_users = app_data.get('users')
            existing_resources = DeviceResourcesDataStore.instance().get_data(device_id=app_id)
            if existing_resources is not None:
                e.protocol_instance.available_resources = existing_resources
                return STATE_READY
            return STATE_GETTING_RESOURCES

        e.status = 'Handshake failed. Invalid signature.'
        return STATE_DISCONNECTED

    @staticmethod
    def on_registered(e):
        if e.error:
            e.status = e.error

        return STATE_APP_REGISTERED if e.verified else STATE_DISCONNECTED

    @staticmethod
    def on_probe_trying(e):
        return STATE_PROBE_TRYING

    @staticmethod
    @verify_header
    def on_getting_resources(e):
        return STATE_REGISTRATION

    @staticmethod
    @verify_header
    def on_getting_probe(e):
        next_state = STATE_READY
        flow = e.protocol_instance.bioauth_flows.get(str(e.request.header.appId))
        if e.request.msg.probeStatus == 'canceled':
            flow.cancel_auth()
            next_state = STATE_READY
            e.protocol_instance.current_probe_request = None
        else:
            tType = str(e.request.msg.tType)
            current_probe_request = e.protocol_instance.current_probe_request
            if current_probe_request.add_next_sample(auth_type=tType,
                                                     samples_list=e.request.msg.probeData.samples):
                if current_probe_request.has_pending_probes(auth_type=tType):
                    next_state = STATE_GETTING_PROBES
                else:
                    message = e.protocol_instance.create_next_message(
                        request_seq=e.request.header.seq,
                        oid='probe',
                        probeStatus='received'
                    )
                    e.protocol_instance.send_message(responce=message)
                    flow.set_probe_results(samples_by_probe_type=current_probe_request.get_samples_by_probe_type())
                    next_state = STATE_READY
                    e.protocol_instance.current_probe_request = None
            else:
                e.status = "Could not add probe samples."
                next_state = STATE_DISCONNECTED

        return next_state

    @staticmethod
    @verify_header
    def on_resources(e):
        resources_dict = {}
        for item in e.request.msg.data:
            resources_dict.update({str(item.rType): str(item.rProperties)})
        logger.debug(msg='RESOURCES: %s available' % resources_dict)
        e.protocol_instance.available_resources = resources_dict
        DeviceResourcesDataStore.instance().store_data(device_id=str(e.request.header.appId), **resources_dict)
        if hasattr(e.request.msg, 'push_token'):
            DeviceInformationStore.instance().update_data(app_id=str(e.request.header.appId),
                                                          push_token=str(e.request.msg.push_token))
        return STATE_READY


def handshake(e):
    if e.request.header.appType == 'probe':
        logger.info(" ------- APP HANDSHAKE: probe")
    else:
        logger.info(" ------- APP HANDSHAKE: extension")

    # Send serverHello responce after entering handshake state
    session = e.protocol_instance.get_current_session()

    message = e.protocol_instance.create_next_message(
        request_seq=e.request.header.seq,
        oid='serverHello',
        refreshToken=session.refresh_token,
        connectionttl=settings.connection_timeout,
        sessionttl=settings.session_ttl
    )

    e.protocol_instance.send_message(responce=message)


def registration(e):
    if e.request.header.appType == 'probe':
        app_type = 'probe'
        logger.info(" -------- APP REGISTRATION: probe")
    else:
        app_type = 'extension'
        logger.info(" -------- APP REGISTRATION: extension")

    secret = str(e.request.msg.secret)
    logger.debug('SECRET: %s' % secret)

    registration_callback = create_registration_callback(fsm=e.fsm, protocol_instance=e.protocol_instance,
                                                         request=e.request)
    ApplicationDataStore.instance().register_application(code=secret, app_type=app_type, callback=registration_callback)


def create_registration_callback(fsm, protocol_instance, request):
    def registration_callback(result):
        verified = result.get('verified', False)
        key = result.get('private_key')
        fingerprint = result.get('app_id')
        error = result.get('error')
        logger.info("REGISTRATION RESULTS: verified: %s, fingerprint: %s, error: %s", verified, fingerprint, error)
        if verified:
            protocol_instance.app_users = result.get('user_id', [])
        fsm.registered(protocol_instance=protocol_instance, request=request, verified=verified, key=key,
                       fingerprint=fingerprint, error=error)

    return registration_callback


def app_registered(e):
    # Send serverHello responce after entering handshake state
    session = e.protocol_instance.get_current_session()

    app_id = str(e.fingerprint)
    protocol_connection_established(protocol_instance=e.protocol_instance, app_id=app_id)

    message = e.protocol_instance.create_next_message(
        request_seq=e.request.header.seq,
        oid='serverHello',
        refreshToken=session.refresh_token,
        sessionttl=settings.session_ttl,
        connectionttl=settings.connection_timeout,
        key=e.key,
        fingerprint=e.fingerprint
    )
    e.protocol_instance.send_message(responce=message)


def ready(e):
    app_type = str(e.request.header.appType)
    app_id = str(e.request.header.appId)
    if (app_type.startswith(PROBE_APP_TYPE_PREFIX) or app_type.startswith(HYBRID_APP_TYPE_PREFIX)) and app_id not in e.protocol_instance.bioauth_flows:
        TriesSimulatorManager.instance().add_active_connection(app_id=app_id, connection_instance=e.protocol_instance,
                                                               user_id=e.protocol_instance.app_users)
        auth_wait_callback = e.protocol_instance.try_probe
        cancel_auth_callback = e.protocol_instance.cancel_auth
        app_users = e.protocol_instance.app_users
        if isinstance(app_users, list):
            app_users = app_users[0]
        bioauth_flow = BioauthFlow(app_type=app_type, app_id=app_id,
                                   try_probe_callback=auth_wait_callback,
                                   cancel_auth_callback=cancel_auth_callback, auto_initialize=False,
                                   app_user=app_users)
        e.protocol_instance.bioauth_flows.update({app_id: bioauth_flow})
        if bioauth_flow.is_probe_owner():
            e.protocol_instance.policy = PolicyManager.get_policy_for_app(app_id=app_id)

        bioauth_flow.initialize()


def probe_trying(e):
    if not e.src == STATE_PROBE_TRYING:
        flow = e.protocol_instance.bioauth_flows.get(str(e.request.header.appId))
        resources = None
        current_resources = e.protocol_instance.available_resources
        if hasattr(e, 'current_resources'):
            if e.current_resources is not None:
                current_resources = e.current_resources
        app_users = e.protocol_instance.app_users
        if isinstance(app_users, list):
            app_users = app_users[0]
        is_training = flow.is_current_state(STATE_AUTH_TRAINING_STARTED)
        policy, resources = PolicyEngineManager.instance().generate_try_resources(
            device_resources=current_resources, user_id=app_users,
            training=is_training)
        if not is_training:
            flow.auth_started(resource_list=e.protocol_instance.available_resources)
        if resources:
            probe_request = ProbeRequest(policy)

            for res in resources:
                auth_type = res.get(FIELD_AUTH_TYPE, None)
                samples_number = res.get(FIELD_SAMPLES_NUM, 0)
                if auth_type is not None and samples_number:
                    probe_request.add_probe(auth_type=auth_type, samples=samples_number)

            e.protocol_instance.current_probe_request = probe_request

            # Send "try" message to probe
            try_message_str = None
            if hasattr(e, 'message'):
                try_message_str = e.message
            try_id = sha1(urandom(32)).hexdigest()[:8]
            if e.protocol_instance._session_id is not None:
                try_id = '%s##%s' % (try_id, e.protocol_instance._session_id)
            message = e.protocol_instance.create_next_message(
                request_seq=e.request.header.seq,
                oid='try',
                try_id=try_id,
                resource=resources,
                policy=policy,
                authTimeout=settings.bioauth_timeout,
                message=try_message_str
            )
            e.protocol_instance.send_message(responce=message)


def getting_probe(e):
    pass


def getting_resouces(e):
    message = e.protocol_instance.create_next_message(
        request_seq=e.request.header.seq,
        oid='getResources'
    )
    e.protocol_instance.send_message(responce=message)


def disconnect(e):
    # If status parameter passed to state change method
    # we will add it as a status for message
    status = None
    if hasattr(e, 'status'):
        status = e.status

    e.protocol_instance.close_connection(status_message=status)


def print_state_change(e):
    """Helper function for printing state transitions to log."""
    logger.info('STATE_TRANSITION: event: %s, %s -> %s' % (e.event, e.src, e.dst))


def protocol_connection_established(protocol_instance, app_id):
    # TODO: make separate method for
    pass


biomio_states = {
    'initial': STATE_CONNECTED,
    'events': [
        {
            'name': 'clientHello',
            'src': STATE_CONNECTED,
            'dst': [STATE_HANDSHAKE, STATE_REGISTRATION, STATE_DISCONNECTED],
            'decision': MessageHandler.on_client_hello_message
        },
        {
            'name': 'ack',
            'src': STATE_APP_REGISTERED,
            'dst': [STATE_GETTING_RESOURCES, STATE_DISCONNECTED],
            'decision': MessageHandler.on_ack_message
        },
        {
            'name': 'registered',
            'src': STATE_REGISTRATION,
            'dst': [STATE_APP_REGISTERED, STATE_DISCONNECTED],
            'decision': MessageHandler.on_registered
        },
        {
            'name': 'resources',
            'src': STATE_GETTING_RESOURCES,
            'dst': [STATE_READY, STATE_DISCONNECTED],
            'decision': MessageHandler.on_resources
        },
        {
            'name': 'nop',
            'src': [STATE_READY, STATE_PROBE_TRYING, STATE_GETTING_PROBES, STATE_GETTING_RESOURCES],
            'dst': [STATE_READY, STATE_PROBE_TRYING, STATE_GETTING_PROBES, STATE_DISCONNECTED, STATE_GETTING_RESOURCES],
            'decision': MessageHandler.on_nop_message
        },
        {
            'name': 'bye',
            'src': [STATE_CONNECTED, STATE_HANDSHAKE, STATE_READY, STATE_PROBE_TRYING, STATE_GETTING_PROBES,
                    STATE_GETTING_RESOURCES, STATE_APP_REGISTERED],
            'dst': STATE_DISCONNECTED,
            'decision': MessageHandler.on_bye_message
        },
        {
            'name': 'auth',
            'src': STATE_HANDSHAKE,
            'dst': [STATE_GETTING_RESOURCES, STATE_DISCONNECTED],
            'decision': MessageHandler.on_auth_message
        },
        {
            'name': 'probetry',
            'src': STATE_READY,
            'dst': [STATE_PROBE_TRYING, STATE_DISCONNECTED],
            'decision': MessageHandler.on_probe_trying
        },
        {
            'name': 'probe',
            'src': [STATE_PROBE_TRYING, STATE_GETTING_PROBES],
            'dst': [STATE_GETTING_PROBES, STATE_READY, STATE_DISCONNECTED],
            'decision': MessageHandler.on_getting_probe
        }
    ],
    'callbacks': {
        'onhandshake': handshake,
        'ondisconnected': disconnect,
        'onregistration': registration,
        'onappregistered': app_registered,
        'onready': ready,
        'onprobetrying': probe_trying,
        'onprobegetting': getting_probe,
        'onresourceget': getting_resouces,
        'onchangestate': print_state_change
    }
}


class BiomioProtocol:
    """ The BiomioProtocol class is an abstraction for protocol implementation.
        For every client connection unique instance of BiomioProtocol is created.
    """

    def __init__(self, **kwargs):
        """
        BiomioProtocol constructor.

        :param close_callback: Will be called when connection should be closed.
        :param send_callback: Will be called when connection should be called with single parameter - message string to send.
        :param start_connection_timer_callback: Will be called when connection timer should be started.
        :param stop_connection_timer_callback: Will be called when connection timer should be stoped.
        :param check_connected_callback: Will be called to check if connected to socket. Should return True if connected.
        """
        # helpful to separate output when auto tests is running
        logger.info(' ===================================================== ')

        self._close_callback = kwargs['close_callback']
        self._send_callback = kwargs['send_callback']
        self._start_connection_timer_callback = kwargs['start_connection_timer_callback']
        self._stop_connection_timer_callback = kwargs['stop_connection_timer_callback']
        self._check_connected_callback = kwargs['check_connected_callback']

        self._session = None
        self._builder = BiomioMessageBuilder(oid='serverHeader', seq=1, protoVer=PROTOCOL_VERSION)

        self._rpc_handler = RpcHandler()

        # Initialize state machine
        self._state_machine_instance = Fysom(biomio_states)

        self._last_received_message = None

        self.policy = None
        self.bioauth_flow = None

        # key - app_id (if not probe device then app_id + _on_behalf_of from rpc), value - bioauthlow instance
        self.bioauth_flows = {}

        self.current_probe_request = None
        self.available_resources = {}

        self.app_users = []

        self.auth_items = []

        self._session_id = None

        logger.debug(' --------- ')  # helpful to separate output when auto tests is running

    @greenado.groutine
    def process_next(self, msg_string):
        """ Processes next message received from client.
        :param msg_string: String containing next message.
        """
        # Next message received - stop connection timer.
        self._stop_connection_timer_callback()

        # Create BiomioMessage instance form message string
        input_msg = None
        try:
            input_msg = self._builder.create_message_from_json(msg_string)
        except ValidationError, e:
            logger.exception('Not valid message - %s' % msg_string)
            logger.exception(e)

        # If message is valid, perform necessary actions
        if input_msg and input_msg.msg and input_msg.header:
            output_str = (msg_string[:256] + '...') if len(msg_string) > 256 else msg_string
            logger.debug('RECEIVED MESSAGE STRING: "%s" ' % output_str)

            # Refresh session if necessary
            if self._session and hasattr(input_msg.header,
                                         'token') and self._session.refresh_token == input_msg.header.token:
                self._refresh_session()

            # Restore session and state (if no session, and message contains token)
            if not self._session and hasattr(input_msg.header, 'token') and input_msg.header.token:
                self._restore_state(refresh_token=str(input_msg.header.token))

            # Try to process RPC request subset, if message is RCP request - exit after processing

            if input_msg.msg.oid in ('rpcReq', 'rpcEnumNsReq', 'rpcEnumCallsReq'):
                self.process_rpc_request(input_msg)
                return

            # Process protocol message
            if not self._state_machine_instance.current == STATE_DISCONNECTED:
                self._process_message(input_msg)
        else:
            self._state_machine_instance.bye(protocol_instance=self,
                                             status='Invalid message sent (message string:%s)' % msg_string)

    def _process_message(self, input_msg):
        """ Processes next message, performs state machine transitions.
        :param input_msg: BiomioMessage instance received from client.
        """
        try:
            # State machine instance has callback with the same name as possible messages, that it could
            # receive from client. Retrieve function object (callback) for message and perform transition.
            logger.info('RECEIVED MESSAGE: "%s" ' % str(input_msg.msg.oid))
            make_transition = getattr(self._state_machine_instance, '%s' % input_msg.msg.oid, None)
            if make_transition:
                if self._state_machine_instance.current == STATE_DISCONNECTED:
                    return

                self._last_received_message = input_msg
                make_transition(request=input_msg, protocol_instance=self)

                # Start connection timer, if state machine does no reach its final state
                if not (self._state_machine_instance.current == STATE_DISCONNECTED):
                    self._start_connection_timer_callback()
            else:
                self._state_machine_instance.bye(request=input_msg, protocol_instance=self,
                                                 status='Could not process message: %s' % input_msg.msg.oid)
        except FysomError, e:
            logger.exception('State event for method not defined')
            self._state_machine_instance.bye(request=input_msg, protocol_instance=self, status=str(e))
        except AttributeError:
            status_message = 'Internal error during processing next message'
            logger.exception(status_message)
            self._state_machine_instance.bye(request=input_msg, protocol_instance=self, status=status_message)

    def create_next_message(self, request_seq=None, status=None, **kwargs):
        """ Helper method to create message for responce.
        :param request_seq: Sequence num of request, got from client. (Will be increased to got next sequence number)
        :param status: Status string for next message.
        :param kwargs: Message parameters.
        :return: BiomioMessage instance.
        """
        if request_seq:
            self._builder.set_header(seq=int(request_seq) + 1)
        message = self._builder.create_message(status=status, **kwargs)
        return message

    def send_message(self, responce):
        """ Helper method for sending given message to client.
        :param responce: BiomioMessage instance to send.
        """
        self._send_callback(responce.serialize())
        logger.info('SENT MESSAGE: "%s" ' % str(responce.msg.oid))
        logger.debug('SENT MESSAGE STRING: %s' % responce.serialize())

    def close_connection(self, status_message=None, is_closed_by_client=False):
        """ Sends bye message and closes session.

        :note Temporary session object will be created to send bye message with status if necessary.

        :param request_seq: Sequence num of request, got from client. (Will be increased to got next sequence number)
        :param status_message: Status string for next message.
        """
        logger.info('CLOSING CONNECTION...')
        self._stop_connection_timer_callback()

        if not is_closed_by_client:
            # Send bye message
            if self._check_connected_callback():
                if not self._session:
                    # Create temporary session object to send bye message if necessary
                    self.start_new_session()

                request_seq = 1
                # Use request seq number from last message if possible
                if self._last_received_message:
                    request_seq = self._last_received_message.header.seq

                message = self.create_next_message(request_seq=request_seq, status=status_message, oid='bye')
                self.send_message(responce=message)

            if self._session and self._session.is_open:
                SessionManager.instance().close_session(session=self._session)

        for app_id, bioauth_flow in self.bioauth_flows.iteritems():
            TriesSimulatorManager.instance().remove_active_connection(app_id=app_id)
            bioauth_flow.shutdown()

        # Close connection
        self._close_callback()

    def get_current_session(self):
        """ Returns current session.
        :return: Session instance.
        """
        return self._session

    def _refresh_session(self):
        """ Used for session refresh and updating session token.
        """
        SessionManager.instance().refresh_session(self._session)
        self._builder.set_header(token=self._session.session_token)

    def is_sequence_valid(self, seq):
        """Checks sequeence number for responce. Return true if it is valid; false otherwise"""
        curr_seq = self._builder.get_header_field_value(field_str='seq')
        return ((int(curr_seq) - 2 < seq)
                or (seq == 0)) and (int(seq) % 2 == 0)

    def is_protocol_version_valid(self, version):
        """Checks protocol version. Return true if it is current version; false otherwise"""
        return version == PROTOCOL_VERSION

    def on_session_closed(self):
        """ Should be called, when session expired.
        """
        self._state_machine_instance.bye(protocol_instance=self, status='Session expired')

    def start_new_session(self):
        """ Starts new session for protocol.
        """
        self._session = SessionManager.instance().create_session(close_callback=self.on_session_closed)
        self._builder.set_header(token=self._session.session_token)

    def connection_closed(self):
        """Should be called in cases when connection is closed by client."""
        if self._session:
            self._session.close_callback = None
            SessionManager.instance().set_protocol_state(token=self._session.refresh_token,
                                                         current_state=self._state_machine_instance.current)
        logger.warning('Connection closed by client')
        self.close_connection(is_closed_by_client=True)

    def _restore_state(self, refresh_token):
        """ Restores session and state machine state using given refresh token. Closes connection with appropriate message otherwice.
        :param refresh_token: Session refresh token string.
        """
        session_manager = SessionManager.instance()
        self._session = session_manager.restore_session(refresh_token)

        if self._session:
            logger.info('Continue session %s...' % refresh_token)
            self._builder.set_header(token=self._session.session_token)
            state = session_manager.get_protocol_state(token=self._session.session_token)
            if state:
                # Restore state
                logger.debug('State : %s' % state)
                self._state_machine_instance.current = state
            else:
                self._state_machine_instance.bye(protocol_instance=self,
                                                 status='Internal error: Could not restore protpcol state after last disconnection')
        else:
            self._state_machine_instance.bye(protocol_instance=self, status='Invalid token')

    def process_rpc_request(self, input_msg):
        message_id = str(input_msg.msg.oid)
        self._last_received_message = input_msg

        if message_id == 'rpcReq':
            data = {}
            if input_msg.msg.data:
                for k, v in izip(list(input_msg.msg.data.keys), list(input_msg.msg.data.values)):
                    data[str(k)] = str(v)

            user_key = ''
            if hasattr(input_msg.msg, 'onBehalfOf'):
                data['on_behalf_of'] = str(input_msg.msg.onBehalfOf)
                user_key = str(input_msg.msg.onBehalfOf)
            if hasattr(input_msg.msg, 'session_id'):
                self._session_id = str(input_msg.msg.session_id)
            namespace = str(input_msg.msg.namespace)
            req_plugin = self._rpc_handler.get_plugin_instance(namespace=namespace)
            user_id = req_plugin.identify_user(on_behalf_of=user_key)
            process_callback_for_rpc_result = self.get_process_callback_for_rpc_result(input_msg=input_msg)
            app_id = str(input_msg.header.appId)
            app_type = str(input_msg.header.appType)
            if user_id is None:
                process_callback_for_rpc_result(status='fail',
                                                result={'error': 'Cannot identify user with key - %s' % user_key})
            else:
                req_plugin.assign_user_to_application(app_id=app_id, user_id=user_id)
                wait_callback = self.send_in_progress_responce
                flow_key = '%s_%s' % (app_id, user_id)
                bioauth_flow = self.bioauth_flows.get(flow_key)
                if bioauth_flow is None:
                    bioauth_flow = BioauthFlow(app_type=app_type, app_id=flow_key,
                                               try_probe_callback=self.try_probe,
                                               cancel_auth_callback=self.cancel_auth)
                    self.bioauth_flows.update({flow_key: bioauth_flow})
                self._rpc_handler.process_rpc_call(
                    str(user_id),
                    str(input_msg.msg.call),
                    str(input_msg.msg.namespace),
                    data,
                    wait_callback,
                    bioauth_flow,
                    app_id,
                    self.get_process_callback_for_rpc_result(input_msg=input_msg)
                )
        elif message_id == 'rpcEnumNsReq':
            namespaces = self._rpc_handler.get_available_namespaces()
            message = self.create_next_message(request_seq=input_msg.header.seq, oid='rpcEnumNsReq',
                                               namespaces=namespaces)
            self.send_message(responce=message)
        elif message_id == 'rpcEnumCallsReq':
            self._rpc_handler.get_available_calls(namespace=input_msg.msg.namespace)

    def get_process_callback_for_rpc_result(self, input_msg):
        def process_rpc_result(**kwargs):
            status = kwargs.get('status', None)
            result = kwargs.get('result', None)

            res_keys = []
            res_values = []

            res_params = {
                'oid': 'rpcResp',
                'onBehalfOf': str(input_msg.msg.onBehalfOf),
                'namespace': str(input_msg.msg.namespace),
                'call': str(input_msg.msg.call),
                'rpcStatus': status
            }

            if self._session_id is not None:
                res_params.update({'session_id': self._session_id})

            if result is not None:
                for k, v in result.iteritems():
                    res_keys.append(k)
                    res_values.append(str(v))

            res_params['data'] = {'keys': res_keys, 'values': res_values}

            message = self.create_next_message(
                request_seq=input_msg.header.seq,
                **res_params
            )
            self.send_message(responce=message)

        return process_rpc_result

    def send_in_progress_responce(self):
        # Should be last RPC request
        input_msg = self._last_received_message

        wait_message = 'To proceed with decryption please open Biomio application on the phone. ' \
                       'Server will wait for 5 minutes to receive results.'

        res_keys = []
        res_values = []

        res_params = {
            'oid': 'rpcResp',
            'onBehalfOf': str(input_msg.msg.onBehalfOf),
            'namespace': str(input_msg.msg.namespace),
            'call': str(input_msg.msg.call),
            'rpcStatus': 'inprogress'
        }

        result = {'msg': wait_message, 'timeout': settings.bioauth_timeout}
        for k, v in result.iteritems():
            res_keys.append(k)
            res_values.append(str(v))

        res_params['data'] = {'keys': res_keys, 'values': res_values}

        message = self.create_next_message(
            request_seq=input_msg.header.seq,
            **res_params
        )
        self.send_message(responce=message)

    def try_probe(self, **kwargs):
        message = kwargs.get('message', None)
        current_resources = kwargs.get('current_resources', None)
        self._state_machine_instance.probetry(request=self._last_received_message, protocol_instance=self,
                                              message=message, current_resources=current_resources)

    def cancel_auth(self, **kwargs):
        flow = kwargs.get('bioauth_flow')
        if flow.is_probe_owner():
            RedisStorage.persistence_instance().delete_data(
                key=REDIS_VERIFICATION_RETIES_COUNT_KEY % flow.app_id)
            RedisStorage.persistence_instance().delete_data(
                key=REDiS_TRAINING_RETRIES_COUNT_KEY % flow.app_id)
            message = self.create_next_message(
                request_seq=self._last_received_message.header.seq,
                oid='probe',
                probeStatus='canceled'
            )
            self.send_message(responce=message)
        self._state_machine_instance.current = STATE_READY
