#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#
# iot-region-to-region-syncer
#

import logging
import os
import sys
import time
import traceback

from concurrent import futures

import boto3

from botocore.config import Config
from device_replication import thing_exists, create_thing_with_cert_and_policy

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
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', 10))

NUM_THINGS_SYNCED = 0
NUM_THINGS_EXIST = 0
NUM_ERRORS = 0

logger.info('PRIMARY_REGION: {} SECONDARY_REGION: {} SYNC_MODE: {} QUERY_STRING: {} MAX_WORKERS: {}'.
    format(PRIMARY_REGION, SECONDARY_REGION, SYNC_MODE, QUERY_STRING, MAX_WORKERS))
logger.info('__name__: {}'.format(__name__))


def sync_thing(c_iot_p, c_iot_s, thing):
    global NUM_THINGS_SYNCED, NUM_THINGS_EXIST, NUM_ERRORS
    try:
        logger.info('thing: {}'.format(thing))
        start_time = int(time.time()*1000)
        thing_name = thing['thingName']

        if SYNC_MODE == "smart":
            if thing_exists(c_iot_s, thing_name):
                logger.info('thing_name {} exists already in secondary region {}'.format(thing_name, SECONDARY_REGION))
                NUM_THINGS_EXIST += 1
                return

        thing_type_name = ""
        if 'thingTypeName' in thing:
            thing_type_name = thing['thingTypeName']

        attrs = {}
        if 'attributes' in thing:
            attrs = {'attributes': {}}
            for key in thing['attributes']:
                attrs['attributes'][key] = thing['attributes'][key]

        if 'attributes' in attrs:
            attrs['merge'] = False

        logger.info('thing_name: {} thing_type_name: {} attrs: {}'.format(thing_name, thing_type_name, attrs))

        create_thing_with_cert_and_policy(c_iot_s, c_iot_p, thing_name, thing_type_name, attrs, 2, 1)
        end_time = int(time.time()*1000)
        duration = end_time - start_time
        NUM_THINGS_SYNCED += 1
        logger.info('sync thing: thing_name: {} duration: {}ms'.format(thing_name, duration))
    except Exception as e:
        logger.error('{}'.format(e))
        NUM_ERRORS += 1
        traceback.print_stack()


def get_next_token(response):
    next_token = None
    if 'nextToken' in response:
        next_token = response['nextToken']

    #logger.info('next_token: {}'.format(next_token))
    return next_token


def get_search_things(c_iot_p, c_iot_s, query_string, max_results, executor):
    logger.info('query_string: {} max_results: {}'.format(query_string, max_results))
    try:
        response = c_iot_p.search_index(
            indexName='AWS_Things',
            queryString=query_string,
            maxResults=max_results
        )

        for thing in response['things']:
            executor.submit(sync_thing, c_iot_p, c_iot_s, thing)

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
                executor.submit(sync_thing, c_iot_p, c_iot_s, thing)
                #sync_thing(c_iot_p, c_iot_s, thing)
    except Exception as e:
        logger.error('{}'.format(e))


def get_list_things(c_iot_p, c_iot_s):
    try:
        paginator = c_iot_p.get_paginator("list_things")

        for page in paginator.paginate():
            logger.debug('page: {}'.format(page))
            logger.debug('things: {}'.format(page['things']))
            for thing in page['things']:
                sync_thing(c_iot_p, c_iot_s, thing)
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
    global NUM_THINGS_SYNCED, NUM_THINGS_EXIST, NUM_ERRORS
    logger.info('event: {}'.format(event))

    NUM_THINGS_SYNCED = 0
    NUM_THINGS_EXIST = 0
    NUM_ERRORS = 0

    if MAX_WORKERS > 50:
        logger.error('max allowed workers is 50 defined: {}'.format(MAX_WORKERS))
        raise Exception('max allowed workers is 50 defined: {}'.format(MAX_WORKERS))

    max_pool_connections = 10
    if MAX_WORKERS >= 10:
        max_pool_connections = round(MAX_WORKERS*1.2)

    logger.info('max_pool_connections: {}'.format(max_pool_connections))

    boto3_config = Config(
        max_pool_connections = max_pool_connections,
        retries = {'max_attempts': 10, 'mode': 'standard'}
    )

    c_iot_p = boto3.client('iot', config=boto3_config, region_name=PRIMARY_REGION)
    c_iot_s = boto3.client('iot', config=boto3_config, region_name=SECONDARY_REGION)

    executor = futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
    logger.info('executor: started: {}'.format(executor))

    if registry_indexing_enabled(c_iot_p):
        logger.info('registry indexing enabled - using search_index to get things')
        get_search_things(c_iot_p, c_iot_s, QUERY_STRING, 100, executor)
    else:
        logger.info('registry indexing disabled - using list_things to get things')
        get_list_things(c_iot_p, c_iot_s)

    logger.info('executor: waiting to finish')
    executor.shutdown(wait=True)
    logger.info('executor: shutted down')

    if SYNC_MODE == "smart":
        logger.info('syncer: stats: NUM_THINGS_SYNCED: {} NUM_THINGS_EXIST: {} NUM_ERRORS: {}'.format(NUM_THINGS_SYNCED, NUM_THINGS_EXIST, NUM_ERRORS))
    else:
        logger.info('syncer: stats: NUM_THINGS_SYNCED: {} NUM_ERRORS: {}'.format(NUM_THINGS_SYNCED, NUM_ERRORS))

    logger.info('syncer: stop')
    return True


# in case we run standalone, e.g. on Fargate
if __name__ == '__main__':
    logger.info('calling lambda_handler')
    lambda_handler({"no": "event"}, None)
