#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#
# iot-region-to-ddb-syncer
#

import hashlib
import json
import logging
import os
import sys
import time
import uuid

import boto3

from botocore.config import Config
from device_replication import thing_exists
from dynamodb_json import json_util as ddb_json

logger = logging.getLogger()
for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
FORMAT = '%(asctime)s [%(levelname)s]: %(threadName)s-%(filename)s:%(lineno)s-%(funcName)s: %(message)s'
h.setFormatter(logging.Formatter(FORMAT))
logger.addHandler(h)
logger.setLevel(logging.INFO)
#logger.setLevel(logging.DEBUG)

PRIMARY_REGION = os.environ['PRIMARY_REGION']
SECONDARY_REGION = os.environ['SECONDARY_REGION']
SYNC_MODE = os.environ.get('SYNC_MODE', 'smart')
QUERY_STRING = os.environ.get('QUERY_STRING', 'thingName:*')
DYNAMODB_GLOBAL_TABLE = os.environ['DYNAMODB_GLOBAL_TABLE']

NUM_THINGS_TO_SYNC = 0
NUM_THINGS_EXIST = 0
NUM_ERRORS = 0

logger.info('PRIMARY_REGION: {} SECONDARY_REGION: {} SYNC_MODE: {} QUERY_STRING: {}'.
    format(PRIMARY_REGION, SECONDARY_REGION, SYNC_MODE, QUERY_STRING))
logger.info('__name__: {}'.format(__name__))


def update_event(c_dynamodb, event):
    global NUM_THINGS_TO_SYNC, NUM_ERRORS
    try:
        response = c_dynamodb.put_item(
            TableName=DYNAMODB_GLOBAL_TABLE,
            Item=event
        )
        logger.info('response: {}'.format(response))
        NUM_THINGS_TO_SYNC += 1
    except Exception as e:
        logger.error("update_table_create_thing_error: {}".format(e))
        NUM_ERRORS += 1


def create_registry_event(c_iot_s, c_dynamodb, thing, account_id):
    global NUM_THINGS_EXIST, NUM_ERRORS
    logger.info('thing: {}'.format(thing))
    try:
        thing_name = thing['thingName']

        if SYNC_MODE == "smart":
            if thing_exists(c_iot_s, thing_name):
                logger.info('thing_name {} exists already in secondary region {}'.format(thing_name, c_iot_s.meta.region_name))
                NUM_THINGS_EXIST += 1
                return

        # "uuid": "{}".format(uuid.uuid4()),
        event = {
            "uuid": "{}".format(hashlib.sha256(thing_name.encode()).hexdigest()),
            "accountId": str(account_id),
            "expires": int(time.time()+172800),
            "eventType" : "THING_EVENT",
            "eventId" : "{}".format(uuid.uuid4()),
            "timestamp" : int(time.time()*1000),
            "operation" : "CREATED"
        }

        event['thingName'] = thing_name

        thing_type_name = ""
        if 'thingTypeName' in thing:
            thing_type_name = thing['thingTypeName']
            event['thingTypeName'] = thing_type_name

        attrs = {}
        if 'attributes' in thing:
            event['attributes'] = {}
            for key in thing['attributes']:
                event['attributes'][key] = thing['attributes'][key]

        logger.info('thing_name: {} thing_type_name: {} attrs: {}'.format(thing_name, thing_type_name, attrs))

        update_event(c_dynamodb, json.loads(ddb_json.dumps(event)))
    except Exception as e:
        logger.error("update_table_create_thing_error: {}".format(e))
        NUM_ERRORS += 1


def get_next_token(response):
    next_token = None
    if 'nextToken' in response:
        next_token = response['nextToken']

    #logger.info('next_token: {}'.format(next_token))
    return next_token


def get_search_things(c_iot_p, c_iot_s, c_dynamodb, account_id, query_string, max_results):
    logger.info('query_string: {} max_results: {}'.format(query_string, max_results))
    try:
        response = c_iot_p.search_index(
            indexName='AWS_Things',
            queryString=query_string,
            maxResults=max_results
        )

        for thing in response['things']:
            create_registry_event(c_iot_s, c_dynamodb, thing, account_id)

        next_token = get_next_token(response)

        while next_token:
            response = c_iot_p.search_index(
                indexName='AWS_Things',
                nextToken=next_token,
                queryString=query_string,
                maxResults=max_results
            )
            next_token = get_next_token(response)

            for thing in response['things']:
                create_registry_event(c_iot_s, c_dynamodb, thing, account_id)

    except Exception as e:
        logger.error('{}'.format(e))


def get_list_things(c_iot_p, c_iot_s, c_dynamodb, account_id):
    try:
        paginator = c_iot_p.get_paginator("list_things")

        for page in paginator.paginate():
            logger.debug('page: {}'.format(page))
            logger.debug('things: {}'.format(page['things']))
            for thing in page['things']:
                create_registry_event(c_iot_s, c_dynamodb, thing, account_id)
    except Exception as e:
        logger.error('{}'.format(e))


def registry_indexing_enabled(c_iot_p):
    try:
        response = c_iot_p.get_indexing_configuration()
        logger.debug('response: {}'.format(response))

        logger.info('thingIndexingMode: {}'.format(response['thingIndexingConfiguration']['thingIndexingMode']))
        if response['thingIndexingConfiguration']['thingIndexingMode'] == 'OFF':
            return False

        return True
    except Exception as e:
        logger.error('{}'.format(e))
        raise Exception(e)


def lambda_handler(event, context):
    logger.info('syncer: start')
    global NUM_THINGS_TO_SYNC, NUM_THINGS_EXIST, NUM_ERRORS
    logger.info('event: {}'.format(event))

    NUM_THINGS_TO_SYNC = 0
    NUM_THINGS_EXIST = 0
    NUM_ERRORS = 0

    boto3_config = Config(
        max_pool_connections = 20,
        retries = {'max_attempts': 10, 'mode': 'standard'}
    )

    c_iot_p = boto3.client('iot', config=boto3_config, region_name=PRIMARY_REGION)
    c_iot_s = boto3.client('iot', config=boto3_config, region_name=SECONDARY_REGION)
    c_dynamodb = boto3.client('dynamodb', region_name=PRIMARY_REGION)

    account_id = boto3.client('sts').get_caller_identity()['Account']

    if registry_indexing_enabled(c_iot_p):
        logger.info('registry indexing enabled - using search_index to get things')
        get_search_things(c_iot_p, c_iot_s, c_dynamodb, account_id, QUERY_STRING, 100)
    else:
        logger.info('registry indexing disabled - using list_things to get things')
        get_list_things(c_iot_p, c_iot_s, c_dynamodb, account_id)

    if SYNC_MODE == "smart":
        logger.info('syncer: stats: NUM_THINGS_TO_SYNC: {} NUM_THINGS_EXIST: {} NUM_ERRORS: {}'.format(NUM_THINGS_TO_SYNC, NUM_THINGS_EXIST, NUM_ERRORS))
    else:
        logger.info('syncer: stats: NUM_THINGS_TO_SYNC: {} NUM_ERRORS: {}'.format(NUM_THINGS_TO_SYNC, NUM_ERRORS))

    logger.info('syncer: stop')
    return True


# in case we run standalone, e.g. on Fargate
if __name__ == '__main__':
    logger.info('calling lambda_handler')
    lambda_handler({"no": "event"}, None)
