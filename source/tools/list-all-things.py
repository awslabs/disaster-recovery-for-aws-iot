#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.

"""IoT DR: list all things
for a given query string."""

import logging
import sys
import time

import boto3

logger = logging.getLogger()
for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
FORMAT = '%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)s - %(funcName)s - %(message)s'
h.setFormatter(logging.Formatter(FORMAT))
logger.addHandler(h)
logger.setLevel(logging.INFO)
#logger.setLevel(logging.DEBUG)


def get_next_token(response):
    next_token = None
    if 'nextToken' in response:
        next_token = response['nextToken']

    #logger.info('next_token: {}'.format(next_token))
    return next_token


def get_search_things(c_iot, query_string, max_results):
    num_things = 0
    try:
        response = c_iot.search_index(
            indexName='AWS_Things',
            queryString=query_string,
            maxResults=max_results
        )

        for thing in response['things']:
            num_things += 1
            logger.info('thing: {}'.format(thing))

        next_token = get_next_token(response)

        while next_token:
            response = c_iot.search_index(
                indexName='AWS_Things',
                nextToken=next_token,
                queryString=query_string,
                maxResults=max_results
            )
            next_token = get_next_token(response)

            for thing in response['things']:
                num_things += 1
                logger.info('thing: {}'.format(thing))

        logger.info('num_things: {} query_string: {}'.format(num_things, query_string))
    except Exception as e:
        logger.error('{}'.format(e))


def get_list_things(c_iot):
    num_things = 0
    try:
        paginator = c_iot.get_paginator("list_things")

        for page in paginator.paginate():
            logger.debug('page: {}'.format(page))
            logger.debug('things: {}'.format(page['things']))
            for thing in page['things']:
                num_things += 1
                logger.info('thing: {}'.format(thing))

        logger.info('num_things: {}'.format(num_things))
    except Exception as e:
        logger.error('{}'.format(e))


def registry_indexing_enabled(c_iot):
    try:
        response = c_iot.get_indexing_configuration()
        logger.debug('response: {}'.format(response))

        logger.info('thingIndexingMode: {}'.format(response['thingIndexingConfiguration']['thingIndexingMode']))
        if response['thingIndexingConfiguration']['thingIndexingMode'] == 'OFF':
            return False

        return True
    except Exception as e:
        logger.error('{}'.format(e))
        raise Exception(e)


def list_all_things(query_string):
    c_iot = boto3.client('iot')
    region = c_iot.meta.region_name

    if registry_indexing_enabled(c_iot):
        logger.info('registry indexing enabled - using search_index to get things: query_string: {}'.format(query_string))
        logger.info('region: {}'.format(region))
        time.sleep(5)
        get_search_things(c_iot, query_string, 100)
    else:
        logger.info('registry indexing disabled - using list_things to get things')
        logger.info('region: {}'.format(region))
        if sys.argv[1]:
            logger.warn('query string not supported when registry indexing is disabled')
        time.sleep(3)
        get_list_things(c_iot)

    return True


# in case we run standalone, e.g. on Fargate
if __name__ == '__main__':
    query_string = 'thingName:*'
    if len(sys.argv) > 1:
        query_string = 'thingName:{}'.format(sys.argv[1])
    list_all_things(query_string)
