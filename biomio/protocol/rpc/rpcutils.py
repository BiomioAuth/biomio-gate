from functools import wraps
import tornado.gen
import inspect

from biomio.protocol.storage.proberesultsstore import ProbeResultsStore
from biomio.protocol.settings import settings

import logging
logger = logging.getLogger(__name__)

CALLBACK_ARG = 'callback'
USER_ID_ARG = 'user_id'
WAIT_CALLBACK_ARG = 'wait_callback'


def _check_rpc_arguments(callable_func, current_kwargs):
    result_kwargs = {}

    def _get_required_args(callable_func):
        args, varargs, varkw, defaults = inspect.getargspec(callable_func)
        if defaults:
            args = args[:-len(defaults)]
        return args

    required_args = _get_required_args(callable_func)

    excluded_params_list = [USER_ID_ARG, CALLBACK_ARG, WAIT_CALLBACK_ARG]
    for k, v in current_kwargs.iteritems():
        if k in excluded_params_list and k not in required_args:
            continue
        else:
            result_kwargs[k] = v

    return result_kwargs


def rpc_call(rpc_func):
    def _decorator(*args, **kwargs):
        callable_kwargs = _check_rpc_arguments(callable_func=rpc_func, current_kwargs=kwargs)
        result = rpc_func(*args, **callable_kwargs)
        status = 'complete'

        # Callback
        callback = kwargs.get(CALLBACK_ARG, None)
        callback(result=result, status=status)
    return wraps(rpc_func)(_decorator)


@tornado.gen.engine
def _is_biometric_data_valid(callable_func, callable_args, callable_kwargs):
    user_id = callable_kwargs.get(USER_ID_ARG, None)
    wait_callback = callable_kwargs.get(WAIT_CALLBACK_ARG, None)
    callback = callable_kwargs.get(CALLBACK_ARG, None)

    try:
        wait_callback()
    except Exception as e:
        callback(result={"error": str(e)}, status='fail')

    if ProbeResultsStore.instance().has_probe_results(user_id=user_id):
        if ProbeResultsStore.instance().get_probe_data(user_id=user_id, key='auth'):
            ProbeResultsStore.instance().remove_probe_data(user_id)

    # Check if there is already connection that waiting for biometric auth
    if ProbeResultsStore.instance().has_probe_results(user_id=user_id):
        is_already_waiting = ProbeResultsStore.instance().get_probe_data(user_id=user_id, key='waiting_auth')
        if not is_already_waiting:
            # Remove existing key, create new
            ProbeResultsStore.instance().remove_probe_data(user_id)
            ProbeResultsStore.instance().store_probe_data(user_id=user_id, ttl=settings.bioauth_timeout, waiting_auth=True)
        else:
            # Another connection is waiting on auth - do nothing, just subscribe later
            pass
    else:
        # There is no key for probe results - create and wait for auth
        ProbeResultsStore.instance().store_probe_data(user_id=user_id, ttl=settings.bioauth_timeout, waiting_auth=True)

    # Create redis key - that will trigger probe try message
    yield tornado.gen.Task(ProbeResultsStore.instance().subscribe_to_data, user_id, 'auth')

    status = None
    user_authenticated = None

    if ProbeResultsStore.instance().has_probe_results(user_id=user_id):
        # Not expired, get probe results
        user_authenticated = ProbeResultsStore.instance().get_probe_data(user_id=user_id, key='auth')
        if not user_authenticated:
            status = 'Biometric authentication failed.'
    else:
        status = 'Biometric auth timeout'

    if user_authenticated:
        kwargs = _check_rpc_arguments(callable_func=callable_func, current_kwargs=callable_kwargs)
        result = callable_func(*callable_args, **kwargs)
        callback(result=result, status='complete')
    else:
        callback(result={"error": status}, status='fail')


def rpc_call_with_auth(rpc_func):
    def _decorator(*args, **kwargs):
        _is_biometric_data_valid(callable_func=rpc_func, callable_args=args, callable_kwargs=kwargs)

    return wraps(rpc_func)(_decorator)
