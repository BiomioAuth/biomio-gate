
from biomio.third_party.fysom import Fysom, FysomError
from biomio.protocol.storage.auth_state_storage import AuthStateStorage
from biomio.protocol.probes.probeauthbackend import ProbeAuthBackend
from biomio.protocol.rpc.app_auth_connection import AppAuthConnection
from biomio.protocol.settings import settings

import tornado.gen

import logging
logger = logging.getLogger(__name__)

STATE_AUTH_READY = 'auth_ready'
STATE_AUTH_WAIT = 'auth_wait'
STATE_AUTH_STARTED = 'auth_started'
STATE_AUTH_SUCCEED = 'auth_succeed'
STATE_AUTH_FAILED = 'auth_failed'
STATE_AUTH_TIMEOUT = 'auth_timeout'
STATE_AUTH_ERROR = 'auth_error'
STATE_AUTH_TRAINING_STARTED = 'auth_training'
STATE_AUTH_TRAINING_DONE = 'auth_training_done'
STATE_AUTH_TRAINING_FAILED = 'auth_training_failed'

# Event callbacks
def on_reset(e):
    return STATE_AUTH_READY


def on_request(e):
    flow = e.bioauth_flow

    if flow.is_extension_owner():
        flow.auth_connection.start_auth()

    return STATE_AUTH_WAIT


def on_start(e):
    return STATE_AUTH_STARTED


def on_probe_available(e):
    flow = e.bioauth_flow

    if not e.fsm.current == STATE_AUTH_ERROR:
        if e.result is not None:
            if e.result:
                return STATE_AUTH_SUCCEED
            else:
                return STATE_AUTH_FAILED
        else:
            return STATE_AUTH_TIMEOUT

    return STATE_AUTH_ERROR


def on_got_results(e):
    return STATE_AUTH_READY


def on_training_results_available(e):
    logger.debug('training results available!')
    return STATE_AUTH_TRAINING_DONE


def on_state_changed(e):
    flow = e.bioauth_flow
    next_state = flow.auth_connection.get_data(key=_PROBESTORE_STATE_KEY)

    if next_state is None:
        if e.fsm.current == STATE_AUTH_STARTED or e.fsm.current == STATE_AUTH_WAIT:
            if flow.auth_connection.get_data():
                next_state = STATE_AUTH_ERROR
                logger.debug('BIOMETRIC AUTH [%s, %s]: AUTH INTERNAL ERROR - state not set')
            else:
                next_state = STATE_AUTH_TIMEOUT
                logger.debug('BIOMETRIC AUTH [%s, %s]: AUTH TIMEOUT')
        else:
            next_state = STATE_AUTH_READY

    logger.debug('BIOMETRIC AUTH [%s, %s]: STATE CHANGED - %s' % (flow.app_type, flow.app_id, next_state))
    return next_state


# State callbacks

def on_auth_wait(e):
    flow = e.bioauth_flow

    if flow.is_probe_owner():
        flow.try_probe_callback(message="Authentication")


def on_auth_training(e):
    flow = e.bioauth_flow
    if flow.is_probe_owner():
        flow.try_probe_callback(message="Training")


def on_auth_finished(e):
    flow = e.bioauth_flow

    if flow.is_extension_owner():
        flow.rpc_callback()


auth_states = {
    'initial': STATE_AUTH_READY,
    'events': [
        {
            'name': 'reset',
            'src': [STATE_AUTH_READY, STATE_AUTH_WAIT, STATE_AUTH_STARTED,
                    STATE_AUTH_SUCCEED, STATE_AUTH_FAILED, STATE_AUTH_TIMEOUT, STATE_AUTH_ERROR,
                    STATE_AUTH_TRAINING_STARTED, STATE_AUTH_TRAINING_DONE, STATE_AUTH_TRAINING_FAILED],
            'dst': [STATE_AUTH_READY],
            'decision': on_reset
        },
        {
            'name': 'request',
            'src': [STATE_AUTH_READY],
            'dst': [STATE_AUTH_WAIT],
            'decision': on_request
        },
        {
            'name': 'start',
            'src': [STATE_AUTH_WAIT],
            'dst': [STATE_AUTH_STARTED],
            'decision': on_start
        },
        {
            'name': 'results_available',
            'src': [STATE_AUTH_STARTED],
            'dst': [STATE_AUTH_SUCCEED, STATE_AUTH_FAILED, STATE_AUTH_TIMEOUT, STATE_AUTH_ERROR],
            'decision': on_probe_available
        },
        {
            'name': 'results_accepted',
            'src': [STATE_AUTH_SUCCEED, STATE_AUTH_FAILED, STATE_AUTH_TIMEOUT, STATE_AUTH_ERROR],
            'dst': [STATE_AUTH_READY],
            'decision': on_got_results
        },
        {
            'name': 'training_results_available',
            'src': [STATE_AUTH_TRAINING_STARTED],
            'dst': [STATE_AUTH_TRAINING_DONE, STATE_AUTH_TRAINING_FAILED],
            'decision': on_training_results_available
        },
        {
            'name': 'state_changed',
            'src': [STATE_AUTH_READY, STATE_AUTH_WAIT, STATE_AUTH_STARTED,
                    STATE_AUTH_SUCCEED, STATE_AUTH_FAILED, STATE_AUTH_TIMEOUT, STATE_AUTH_ERROR,
                    STATE_AUTH_TRAINING_STARTED, STATE_AUTH_TRAINING_DONE, STATE_AUTH_TRAINING_FAILED],
            'dst': [STATE_AUTH_READY, STATE_AUTH_WAIT, STATE_AUTH_STARTED, STATE_AUTH_SUCCEED,
                    STATE_AUTH_FAILED, STATE_AUTH_TIMEOUT, STATE_AUTH_ERROR,
                    STATE_AUTH_TRAINING_STARTED, STATE_AUTH_TRAINING_DONE, STATE_AUTH_TRAINING_FAILED],
            'decision': on_state_changed
        }
    ],
    'callbacks': {
        'onauth_wait': on_auth_wait,
        'onauth_succeed': on_auth_finished,
        'onauth_failed': on_auth_finished,
        'onauth_timeout': on_auth_finished,
        'onauth_error': on_auth_finished,
        'onauth_training': on_auth_training
    }
}

_PROBESTORE_STATE_KEY = 'state'


# Helper Methods
def _store_state(e):
    data = {_PROBESTORE_STATE_KEY: e.fsm.current}
    flow = e.bioauth_flow
    flow.auth_connection.store_data(**data)


class BioauthFlow:
    def __init__(self, app_type, app_id, try_probe_callback, auto_initialize=True):
        self.app_type = app_type
        self.app_id = app_id
        self.rpc_callback = None
        self.try_probe_callback = try_probe_callback
        self.status = None

        self._state_machine_instance = Fysom(auth_states)
        self._state_machine_instance.onchangestate = self._get_state_machine_logger_callback()
        self._change_state_callback = self._get_change_state_callback()

        self._resources_list = []

        self.auth_connection = AppAuthConnection(app_id=app_id, app_type=app_type)

        if auto_initialize:
            self.initialize()

    def initialize(self):
        logger.debug('BIOMETRIC AUTH OBJECT [%s, %s]: INITIALIZING...' % (self.app_type, self.app_id))
        self.auth_connection.set_app_connected(app_auth_data_callback=self._change_state_callback)
        self._restore_state()

    def shutdown(self):
        logger.debug('BIOMETRIC AUTH OBJECT [%s, %s]: SHUTTING DOWN...' % (self.app_type, self.app_id))
        self.auth_connection.set_app_disconnected()
        if self.is_extension_owner():
            self.reset()
        self._store_state()

    def _get_state_machine_logger_callback(self):
        def _state_machine_logger(e):
            flow = self
            logger.debug('BIOMETRIC AUTH [%s, %s]: %s -> %s' % (flow.app_type, flow.app_id, e.src, e.dst))

        return _state_machine_logger

    def _get_change_state_callback(self):

        def _state_changed(*args, **kwargs):
            flow = self
            if flow is not None:
                flow._state_machine_instance.state_changed(bioauth_flow=self)

        return _state_changed

    def _restore_state(self):
        """
        Restores BioauthFlow object state by probe results key by given user id.
        """
        logger.debug("Restoring state for bioauth flow: %s, %s" % (self.app_type, self.app_id))
        try:
            self._change_state_callback()
            logger.debug("State to restore: %s" % self._state_machine_instance.current)
        except Exception as e:
            logger.exception("Failed to restore state")

    def _store_state(self):
        data = {_PROBESTORE_STATE_KEY: self._state_machine_instance.current}
        self.auth_connection.store_data(**data)

    def reset(self):
        self._state_machine_instance.reset(bioauth_flow=self)
        self._store_state()

    @tornado.gen.engine
    def request_auth(self, callback):
        """
        Should be called for extension to request biometric authentication from probe.
        """
        self.rpc_callback = callback # Store callback to call later in STATE_AUTH_FINISHED state
        self._state_machine_instance.request(bioauth_flow=self)
        self._store_state()

    def auth_started(self, resource_list=None):
        self._resources_list = resource_list
        self._state_machine_instance.start(bioauth_flow=self)
        self._store_state()

    @tornado.gen.engine
    def set_next_auth_result(self, appId, type, data):
        if not self._resources_list:
            logger.warning(msg='resource item list for probe is empty')
        result = yield tornado.gen.Task(ProbeAuthBackend.instance().probe, type, data, self.app_id, False)
        logger.debug(msg='SET NEXT AUTH RESULT: %s' % str(result))
        #TODO: count probes and set appropriate result
        self.set_auth_results(result=result)
        self._store_state()

    @tornado.gen.engine
    def set_auth_training_results(self, appId, type, data):
        if self._state_machine_instance.current == STATE_AUTH_TRAINING_STARTED:
            result = yield tornado.gen.Task(ProbeAuthBackend.instance().probe, type, data, self.app_id, True)
            logger.debug(msg='TRAINING RESULT: %s' % str(result))
        self._state_machine_instance.training_results_available()
        self._store_state()

    def set_auth_results(self, result):
        #TODO: make method private
        self._state_machine_instance.results_available(bioauth_flow=self, result=result)
        self._store_state()

    def accept_results(self):
        self._state_machine_instance.results_accepted(bioauth_flow=self)
        self._store_state()

    def is_current_state(self, state):
        return self._state_machine_instance.current == state

    def is_probe_owner(self):
        return self.auth_connection.is_probe_owner()

    def is_extension_owner(self):
        return self.auth_connection.is_extension_owner()

    @classmethod
    def start_training(cls, app_id):
        data = {_PROBESTORE_STATE_KEY: STATE_AUTH_TRAINING_STARTED}
        app_id = 'auth:3a9d3f79ecc2c42b9114b4300a248777:88b960b1c9805fb586810f270def7378'
        AuthStateStorage.instance().store_probe_data(app_id, ttl=settings.bioauth_timeout, **data)
        print 'start learning process...'

