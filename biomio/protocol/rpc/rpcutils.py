from functools import wraps
import tornado.gen
import inspect

from biomio.protocol.storage.redissubscriber import RedisSubscriber
from biomio.protocol.storage.proberesultsstore import ProbeResultsStore
from biomio.protocol.settings import settings


def set_probe_result(user_id, auth_successfull):
    ProbeResultsStore.instance().store_probe_data(user_id=user_id, ttl=settings.bioauth_timeout, auth=auth_successfull)


def _callback_arg(callable_kwargs):
    return callable_kwargs.get('callback', None)


def _user_id_arg(callable_kwargs):
    return callable_kwargs.get('user_id', None)


def _check_rpc_arguments(callable_func, current_kwargs):
    result_kwargs = {}

    def _get_required_args(callable_func):
        args, varargs, varkw, defaults = inspect.getargspec(callable_func)
        if defaults:
            args = args[:-len(defaults)]
        return args

    required_args = _get_required_args(callable_func)

    for k, v in current_kwargs.iteritems():
        if k in ['user_id', 'callback'] and k not in required_args:
            continue
        else:
            result_kwargs[k] = v

    return result_kwargs


def rpc_call(rpc_func):
    def _decorator(*args, **kwargs):
        callable_kwargs = _check_rpc_arguments(callable_func=rpc_func, current_kwargs=kwargs)
        result = rpc_func(*args, **callable_kwargs)

        # Callback
        callback = _callback_arg(callable_kwargs=kwargs)
        callback(result)
    return wraps(rpc_func)(_decorator)


@tornado.gen.engine
def _is_biometric_data_valid(callable_func, callable_args, callable_kwargs):
    user_id = _user_id_arg(callable_kwargs=callable_kwargs)

    ProbeResultsStore.instance().store_probe_data(user_id=user_id, ttl=settings.bioauth_timeout, auth=False)
    yield tornado.gen.Task(RedisSubscriber.instance().subscribe, user_id)

    status = None
    user_authenticated = None

    if ProbeResultsStore.instance().has_probe_results(user_id=user_id):
        # Not expired, get probe results
        user_authenticated = ProbeResultsStore.instance().get_probe_data(user_id=user_id, key='auth')
        if not user_authenticated:
            status = 'Biometric authentication failed.'
    else:
        status = 'Biometric auth timeout'

    callback = _callback_arg(callable_kwargs)

    if user_authenticated:
        kwargs = _check_rpc_arguments(callable_func=callable_func, current_kwargs=callable_kwargs)
        result = callable_func(*callable_args, **kwargs)
        callback(result)
    else:
        callback({"status": status})
        pass


def rpc_call_with_auth(rpc_func):
    def _decorator(*args, **kwargs):
        _is_biometric_data_valid(callable_func=rpc_func, callable_args=args, callable_kwargs=kwargs)

    return wraps(rpc_func)(_decorator)
