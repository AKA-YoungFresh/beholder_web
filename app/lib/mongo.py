# -*- coding: UTF-8 -*-
from pymongo import MongoClient


class MongoDB(object):
    def __init__(self, host='localhost', port=27017, database='', username='', password=''):

        self.host = host
        self.port = port
        self.database = database

        if username and password:
            self._conn = MongoClient(
                'mongodb://%s:%s@%s:%s/' % (username, password, self.host, self.port), connect=False)
        else:
            self._conn = MongoClient(host=self.host, port=self.port, connect=False)

        self.coll = self._conn[self.database]
