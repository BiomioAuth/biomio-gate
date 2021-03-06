from biomio.constants import MYSQL_IDENTIFICATION_HASH_DATA_TABLE_NAME, MYSQL_IDENTIFICATION_USER_HASH_TABLE_NAME
from database_actions import delete_data, create_records, select_records_by_ids
from biomio.algorithms.cvtools.types import numpy_ndarrayToList, isEqual
from biomio.protocol.storage.redis_storage import RedisStorage
from biomio.worker.worker_interface import WorkerInterface
from defs import serialize, deserialize
from threading import Lock
import ast
from biomio.algorithms.logger import logger


REDIS_IDENTIFICATION_BUCKET_KEY = 'identification_hash:%s:%s'
HASH_BUCKET_KEY_FORMAT = "bucket_key:%s:%s"


class AlgorithmsHashRedisStackStore:
    _instance = None
    _lock = Lock()

    def __init__(self, redis_id):
        self._ihr_redis = RedisStorage.ihr_instance(redis_id)
        self._hash_data_table_name = MYSQL_IDENTIFICATION_HASH_DATA_TABLE_NAME
        self._user_hash_table_name = MYSQL_IDENTIFICATION_USER_HASH_TABLE_NAME

        self._worker = WorkerInterface.instance()

    @classmethod
    def instance(cls, redis_id):
        with cls._lock:
            if cls._instance is None:
                cls._instance = AlgorithmsHashRedisStackStore(redis_id)
        return cls._instance

    def store_vectors(self, hash_data_list, data, data_id=None, callback=None):
        user_hash_data = []
        local_buckets_list = []
        hash_keys_data = {}
        ext_data_key = str(data)
        if data_id is not None:
            ext_data_key += ':' + str(data_id)
        for hash_name, hash_buckets in hash_data_list:
            for key, value in hash_buckets:
                bucket_key = HASH_BUCKET_KEY_FORMAT % (hash_name, key)
                if not local_buckets_list.__contains__(bucket_key):
                    local_buckets_list.append(bucket_key)
                    user_hash_data.append((ext_data_key, str(bucket_key)))
                values = hash_keys_data.get(str(bucket_key), [])
                contains = False
                for v in values:
                    if isEqual(v[0], numpy_ndarrayToList(value)) and str(v[1]) == str(data):
                        contains = True
                        break
                if not contains:
                    values.append((numpy_ndarrayToList(value), str(data)))
                hash_keys_data[str(bucket_key)] = values

        user_records = select_records_by_ids(self._user_hash_table_name, [ext_data_key], True)
        if len(user_records['records']) > 0:
            loaded_buckets = []
            for record in user_records['records']:
                if not loaded_buckets.__contains__(str(record['bucket_key'])):
                    loaded_buckets.append(str(record['bucket_key']))
            hash_buckets = select_records_by_ids(self._hash_data_table_name, loaded_buckets)
            delete_data(self._user_hash_table_name, [ext_data_key])
            for key, value in hash_buckets.iteritems():
                hash_data = deserialize(value['hash_data'])
                logger.debug(hash_data)
                hash_buckets[key] = [v for v in hash_data if v[1] != str(data)]
            for key, value in hash_keys_data.iteritems():
                values = hash_buckets.get(key, [])
                for v in value:
                    values.append(v)
                hash_buckets[key] = values
            if len(hash_buckets.keys()) > 0:
                remove_keys_list = []
                hash_buckets_list = []
                for key, value in hash_buckets.iteritems():
                    if len(value) > 0:
                        hash_buckets_list.append((str(key), serialize(value)))
                    else:
                        remove_keys_list.append(str(key))
                if len(remove_keys_list) > 0:
                    delete_data(self._hash_data_table_name, remove_keys_list)
                if len(hash_buckets_list) > 0:
                    create_records(self._hash_data_table_name, tuple(hash_buckets_list), True)
        if len(user_hash_data) > 0:
            create_records(self._user_hash_table_name, tuple(user_hash_data))

    def load_data(self, user_ids=None, data_id=None, user_group_id=None, include_only_from=None):
        if user_ids is None:
            user_ids = select_records_by_ids("", [user_group_id], True)
        if len(user_ids) > 0:
            data_user_ids = []
            for user_id in user_ids:
                user_data_id = str(user_id)
                if data_id is not None:
                    user_data_id += ":" + str(data_id)
                data_user_ids.append(user_data_id)
            user_records = select_records_by_ids(self._user_hash_table_name, data_user_ids, True)
            logger.debug(user_records)
            if len(user_records['records']) > 0:
                loaded_buckets = []
                for record in user_records['records']:
                    if not loaded_buckets.__contains__(str(record['bucket_key'])):
                        if include_only_from is not None:
                            if include_only_from.__contains__(self._buckets_hash(str(record['bucket_key']))):
                                loaded_buckets.append(str(record['bucket_key']))
                        else:
                            loaded_buckets.append(str(record['bucket_key']))

                hash_buckets = select_records_by_ids(self._hash_data_table_name, loaded_buckets)
                logger.debug(hash_buckets)
                for key, value in hash_buckets.iteritems():
                    hash_data = deserialize(value['hash_data'])
                    if self._ihr_redis.exists(str(key)):
                        self._ihr_redis.delete_data(str(key))
                    self._ihr_redis.store_data(key=str(key), **{'data': hash_data})

    @staticmethod
    def _buckets_hash(key):
        parts = key.split(':')
        return parts[1] if len(parts) == 3 else ""

    def get_bucket(self, hash_name, bucket_key):
        redis_key = HASH_BUCKET_KEY_FORMAT % (hash_name, bucket_key)
        logger.debug(redis_key)
        data = self._ihr_redis.get_data(redis_key)
        logger.debug(data)
        if data is not None:
            data = ast.literal_eval(data)
            return data['data']
        else:
            return []

    def _select_data_by_ids(self, table_class_name, object_ids, callback):
        """
            Internal methods which selects data from MySQL table by given list of ids.
        :param table_class_name: str Pony MySQL Entity class name.
        :param object_ids:  list of object ids to get data for.
        :param callback: function that must be executed after we got data.
        """
        self._run_storage_job(self._worker.SELECT_JOB, callback, table_class_name=table_class_name,
                              object_ids=object_ids)

    def _run_storage_job(self, job_to_run, callback=None, kwargs_list_for_results_gatherer=None, **kwargs):
        """
            Runs given job with specified kwargs.
        :param job_to_run: storage job that we will run using worker.
        :param kwargs: input parameters for job.
        """
        self._worker.run_job(job_to_run=job_to_run, callback=callback,
                             kwargs_list_for_results_gatherer=kwargs_list_for_results_gatherer, **kwargs)
