from __future__ import absolute_import
from biomio.constants import REDIS_PROBE_RESULT_KEY, REDIS_RESULTS_COUNTER_KEY, REDIS_PARTIAL_RESULTS_KEY, \
    REST_REGISTER_BIOMETRICS, get_ai_training_response, TRAINING_STARTED_STATUS, TRAINING_STARTED_MESSAGE, \
    REDIS_UPDATE_TRAINING_KEY, REDIS_VERIFICATION_RETIES_COUNT_KEY, REDiS_TRAINING_RETRIES_COUNT_KEY, \
    TRAINING_RETRY_STATUS, TRAINING_RETRY_MESSAGE, TRAINING_SUCCESS_STATUS, TRAINING_SUCCESS_MESSAGE, \
    TRAINING_FAILED_STATUS, TRAINING_FAILED_MESSAGE, TRAINING_MAX_RETRIES_STATUS, TRAINING_MAX_RETRIES_MESSAGE
from biomio.protocol.data_stores.algorithms_data_store import AlgorithmsDataStore
from biomio.protocol.probes.plugins.face_verify_plugin.defs import APP_ROOT
from biomio.algorithms.plugins_tools import store_test_photo_helper, get_algo_db, save_images, store_training_db
from biomio.protocol.settings import settings as biomio_settings
from requests.exceptions import HTTPError
from logger import worker_logger
import requests
import tempfile
import shutil
import base64
import json


def pre_training_helper(images, probe_id, settings, callback_code, try_type, ai_code):
    worker_logger.info('Running training for user - %s, with given parameters - %s' % (settings.get('userID'),
                                                                                       settings))
    ai_response_type = dict()
    try:
        worker_logger.info('Telling AI that we are starting training with code - %s' % ai_code)
        ai_response_type.update({'status': TRAINING_STARTED_STATUS, 'message': TRAINING_STARTED_MESSAGE})
        response_type = base64.b64encode(json.dumps(ai_response_type))
        register_biometrics_url = biomio_settings.ai_rest_url % (REST_REGISTER_BIOMETRICS % (ai_code, response_type))
        response = requests.post(register_biometrics_url)
        try:
            response.raise_for_status()
            worker_logger.info('AI should now know that training started with code - %s and response type - %s' %
                               (ai_code, response_type))
        except HTTPError as e:
            worker_logger.exception(e)
            worker_logger.exception('Failed to tell AI that training started, reason - %s' % response.reason)
    except Exception as e:
        worker_logger.error('Failed to build rest request to AI - %s' % str(e))
        worker_logger.exception(e)
    ai_response_type.update({'status': TRAINING_SUCCESS_STATUS, 'message': TRAINING_SUCCESS_MESSAGE})
    result = False
    error = None
    if AlgorithmsDataStore.instance().exists(key=REDIS_UPDATE_TRAINING_KEY % probe_id):
        settings.update({'database': get_algo_db(probe_id=probe_id)})
        AlgorithmsDataStore.instance().delete_data(key=REDIS_UPDATE_TRAINING_KEY % probe_id)
    temp_image_path = tempfile.mkdtemp(dir=APP_ROOT)
    try:
        image_paths = save_images(images, temp_image_path)

        # Store photos for test purposes
        store_test_photo_helper(APP_ROOT, image_paths)

        settings.update({'data': image_paths})
        settings.update({'general_data': {'data_path': temp_image_path,
                                          'ai_code': ai_code,
                                          'try_type': try_type,
                                          'probe_id': probe_id}})
        return settings
    except:
        final_helper(temp_image_path, probe_id, error, callback_code, result, ai_response_type, try_type, ai_code)
        return None


def result_training_helper(algo_result, callback_code, probe_id, temp_image_path, try_type, ai_code):
    ai_response_type = dict()
    ai_response_type.update({'status': TRAINING_SUCCESS_STATUS, 'message': TRAINING_SUCCESS_MESSAGE})
    result = False
    error = None
    try:
        if isinstance(algo_result, dict) and algo_result.get('status', '') == "update":
            # record = dictionary:
            # key          value
            #      'status'     "update"
            #      'userID'     Unique user identificator
            #      'algoID'     Unique algorithm identificator
            #      'database'   BLOB data of user, with userID, for verification algorithm algoID
            #
            # Need update record in algorithms database or create record for user userID and algorithm
            # algoID if it doesn't exists
            database = algo_result.get('database', None)
            if database is not None:
                store_training_db(database, probe_id)
                result = True
                ai_response_type.update(dict(
                    status=TRAINING_SUCCESS_STATUS,
                    message=TRAINING_SUCCESS_MESSAGE
                ))
        elif isinstance(algo_result, list):
            for algo_result_item in algo_result:
                if algo_result_item.get('status', '') == "error":
                    worker_logger.exception('Error during education - %s, %s, %s' % (algo_result_item.get('status'),
                                                                                     algo_result_item.get('type'),
                                                                                     algo_result_item.get('details')))
                    if 'Internal Training Error' in algo_result_item.get('type', ''):
                        error = algo_result_item.get('details', {}).get('message', '')
                        ai_response_type.update(dict(
                            status=TRAINING_RETRY_STATUS,
                            message=TRAINING_RETRY_MESSAGE
                        ))
                    else:
                        ai_response_type.update({'status': 'error'})

                elif algo_result_item.get('status', '') == 'update':
                    database = algo_result_item.get('database', None)
                    if database is not None:
                        store_training_db(database, probe_id)
                        result = True
                        ai_response_type.update(dict(
                            status=TRAINING_SUCCESS_STATUS,
                            message=TRAINING_SUCCESS_MESSAGE
                        ))
            # record = dictionary:
            # key          value
            #      'status'     "error"
            #      'type'       Type of error
            #      'userID'     Unique user identificator
            #      'algoID'     Unique algorithm identificator
            #      'details'    Error details dictionary
            #
            # Algorithm can have three types of errors:
            #       "Algorithm settings are empty"
            #        in this case fields 'userID', 'algoID', 'details' are empty
            #       "Invalid algorithm settings"
            #        in this case 'details' dictionary has following structure:
            #               key         value
            #               'params'    Parameters key ('data')
            #               'message'   Error message (for example "File <path> doesn't exists")
            #       "Internal algorithm error"
            # Need save to redis
            pass
        elif algo_result.get('status', '') == "error":
            worker_logger.exception('Error during education - %s, %s, %s' % (algo_result.get('status'),
                                                                             algo_result.get('type'),
                                                                             algo_result.get('details')))
            if 'Internal Training Error' in algo_result.get('type', ''):
                error = algo_result.get('details', {}).get('message', '')
                ai_response_type.update(dict(
                    status=TRAINING_RETRY_STATUS,
                    message=TRAINING_RETRY_MESSAGE
                ))
            else:
                ai_response_type.update({'status': 'error'})
                ai_response_type.update(dict(
                    status=TRAINING_FAILED_STATUS,
                    message=TRAINING_FAILED_MESSAGE
                ))
            # record = dictionary:
            # key          value
            #      'status'     "error"
            #      'type'       Type of error
            #      'userID'     Unique user identificator
            #      'algoID'     Unique algorithm identificator
            #      'details'    Error details dictionary
            #
            # Algorithm can have three types of errors:
            #       "Algorithm settings are empty"
            #        in this case fields 'userID', 'algoID', 'details' are empty
            #       "Invalid algorithm settings"
            #        in this case 'details' dictionary has following structure:
            #               key         value
            #               'params'    Parameters key ('data')
            #               'message'   Error message (for example "File <path> doesn't exists")
            #       "Internal algorithm error"
            # Need save to redis
            pass
    except Exception as e:
        worker_logger.exception(e)
    finally:
        final_helper(temp_image_path, probe_id, error, callback_code, result, ai_response_type, try_type, ai_code)


def final_helper(temp_image_path, probe_id, error, callback_code, result, ai_response_type, try_type, ai_code):
    shutil.rmtree(temp_image_path)
    if error is not None:
        retries_count = AlgorithmsDataStore.instance().decrement_int_value(
            REDiS_TRAINING_RETRIES_COUNT_KEY % probe_id)
        if retries_count == 0:
            AlgorithmsDataStore.instance().delete_data(key=REDiS_TRAINING_RETRIES_COUNT_KEY % probe_id)
            worker_logger.debug('Maximum training attempts reached...')
            result = False
            ai_response_type.update(dict(
                status=TRAINING_MAX_RETRIES_STATUS,
                message=TRAINING_MAX_RETRIES_MESSAGE
            ))
            # _tell_ai_training_results(result, ai_response_type, try_type, ai_code)
        else:
            AlgorithmsDataStore.instance().store_data(key=REDIS_UPDATE_TRAINING_KEY % probe_id, error=error)
            result = dict(result=False, error=error)
        AlgorithmsDataStore.instance().store_data(key=REDIS_PROBE_RESULT_KEY % callback_code, result=result)
        worker_logger.info('Job was finished with internal algorithm error %s ' % error)
    else:
        AlgorithmsDataStore.instance().delete_data(key=REDiS_TRAINING_RETRIES_COUNT_KEY % probe_id)
        AlgorithmsDataStore.instance().store_data(key=REDIS_PROBE_RESULT_KEY % callback_code, result=result)
    _tell_ai_training_results(result, ai_response_type, try_type, ai_code)


def store_verification_results(result, callback_code, probe_id):
    if 'error' in result:
        retries_count = AlgorithmsDataStore.instance().decrement_int_value(
            REDIS_VERIFICATION_RETIES_COUNT_KEY % probe_id)
        if retries_count == 0:
            AlgorithmsDataStore.instance().delete_data(key=REDIS_VERIFICATION_RETIES_COUNT_KEY % probe_id)
            worker_logger.debug('Max number of verification attempts reached...')
            del result['error']
            result.update({'max_retries': True})
    else:
        AlgorithmsDataStore.instance().delete_data(key=REDIS_VERIFICATION_RETIES_COUNT_KEY % probe_id)
    AlgorithmsDataStore.instance().delete_data(key=REDIS_RESULTS_COUNTER_KEY % callback_code)
    AlgorithmsDataStore.instance().delete_data(key=REDIS_PARTIAL_RESULTS_KEY % callback_code)
    AlgorithmsDataStore.instance().store_data(key=REDIS_PROBE_RESULT_KEY % callback_code, result=result)


def _tell_ai_training_results(result, ai_response_type, try_type, ai_code):
    if isinstance(result, bool) and result:
        ai_response_type.update(get_ai_training_response(try_type))
    try:
        worker_logger.info('Telling AI that training is finished with code - %s and result - %s' %
                           (ai_code, result))
        response_type = base64.b64encode(json.dumps(ai_response_type))
        register_biometrics_url = biomio_settings.ai_rest_url % (REST_REGISTER_BIOMETRICS %
                                                                 (ai_code, response_type))
        response = requests.post(register_biometrics_url)
        try:
            response.raise_for_status()
            worker_logger.info(
                'AI should now know that training is finished with code - %s and response type - %s' %
                (ai_code, response_type))
        except HTTPError as e:
            worker_logger.exception(e)
            worker_logger.exception(
                'Failed to tell AI that training is finished, reason - %s' % response.reason)
    except Exception as e:
        worker_logger.error('Failed to build rest request to AI - %s' % str(e))
        worker_logger.exception(e)
