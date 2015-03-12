import datetime
import pony.orm as pny
import abc

database = pny.Database()
pny.sql_debug(True)


class BaseEntityClass(database.Entity):
    create_date = pny.Required(datetime, sql_default='CURRENT_TIMESTAMP')

    __metaclass__ = abc.ABCMeta

    @staticmethod
    @abc.abstractmethod
    def get_redis_key(key_value):
        """
            Returns Redis key for current table type.
        :param key_value: Value that is used to generate the redis key.
        :return: str redis key.

        """
        return

    @staticmethod
    @abc.abstractmethod
    def get_unique_search_attribute():
        """
            Returns default unique search attribute for current table type.
        :return: str unique attribute.

        """
        return

    @staticmethod
    @abc.abstractmethod
    def create_record(**kwargs):
        """
            Creates record inside current table.
        :param kwargs: param/value dictionary.
        """


class UserInformation(BaseEntityClass):
    user_id = pny.Required(str, unique=True)
    name = pny.Optional(str, nullable=True)
    emails = pny.Set('EmailPGPInformation')
    applications = pny.Set('AppInformation')

    @staticmethod
    def get_redis_key(user_id):
        return 'user:%s' % user_id

    @staticmethod
    def get_unique_search_attribute():
        return 'user_id'

    @staticmethod
    def create_record(**kwargs):
        UserInformation(**kwargs)


class EmailPGPInformation(BaseEntityClass):
    email = pny.Required(str, unique=True)
    pass_phrase = pny.Required(str)
    public_pgp_key = pny.Required(str)
    private_pgp_key = pny.Optional(str, nullable=True)
    user = pny.Required(UserInformation)

    @staticmethod
    def get_redis_key(email):
        return 'user_email:%s' % email

    @staticmethod
    def get_unique_search_attribute():
        return 'email'

    @staticmethod
    def create_record(**kwargs):
        if 'user' in kwargs:
            search_query = {UserInformation.get_unique_search_attribute(): kwargs.get('user')}
            user = UserInformation.get(**search_query)
            kwargs.update({'user': user})
        EmailPGPInformation(**kwargs)


class AppInformation(BaseEntityClass):
    app_id = pny.Required(str, unique=True)
    app_public_key = pny.Required(str)
    users = pny.Set(UserInformation)

    @staticmethod
    def get_redis_key(app_id):
        return 'acount:%s:%s' % ('id', app_id)

    @staticmethod
    def get_unique_search_attribute():
        return 'app_id'

    @staticmethod
    def create_record(**kwargs):
        print kwargs
        if 'users' in kwargs:
            search_query = {UserInformation.get_unique_search_attribute(): kwargs.get('users')}
            user = UserInformation.get(**search_query)
            kwargs.update({'users': [user]})
        AppInformation(**kwargs)


class ChangesTable(BaseEntityClass):
    redis_key = pny.Required(str, unique=True)

    @staticmethod
    def create_record(**kwargs):
        ChangesTable(**kwargs)

    @staticmethod
    def get_redis_key(key_value):
        return ''

    @staticmethod
    def get_unique_search_attribute():
        return 'redis_key'