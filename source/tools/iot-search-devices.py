#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.

import argparse
import boto3
import json
import logging
import sys

logger = logging.getLogger()
for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
FORMAT = '%(asctime)s [%(levelname)s]: %(threadName)s-%(filename)s:%(lineno)s-%(funcName)s: %(message)s'
h.setFormatter(logging.Formatter(FORMAT))
logger.addHandler(h)
logger.setLevel(logging.INFO)
#logger.setLevel(logging.DEBUG)

parser = argparse.ArgumentParser(description="List all things for a given query string.")
parser.add_argument('--query-string', required=True, help="Query string.")
args = parser.parse_args()

NUM_THINGS = 0


def print_response(response):
    del response['ResponseMetadata']
    logger.info(json.dumps(response, indent=2, default=str))
    

def get_next_token(response):
    next_token = None
    if 'nextToken' in response:
        next_token = response['nextToken']

    #logger.info('next_token: {}'.format(next_token))
    return next_token


def search_things(max_results):
    global NUM_THINGS
    logger.info('args.query_string: {} max_results: {}'.format(args.query_string, max_results))
    try:
        session = boto3.Session()
        region = session.region_name
        c_iot = session.client('iot')
        response = c_iot.search_index(
            indexName='AWS_Things',
            queryString=args.query_string,
            maxResults=max_results
        )

        for thing in response['things']:
            logger.info('region: {} thing: {}'.format(region, thing))
            NUM_THINGS += 1

        next_token = get_next_token(response)

        while next_token:
            session = boto3.Session()
            region = session.region_name
            c_iot = session.client('iot')
            response = c_iot.search_index(
                indexName='AWS_Things',
                nextToken=next_token,
                queryString=args.query_string,
                maxResults=max_results
            )
            next_token = get_next_token(response)

            for thing in response['things']:
                logger.info('region: {} thing: {}'.format(region, thing))
                NUM_THINGS += 1
                
    except Exception as e:
        logger.error('{}'.format(e))


def registry_indexing_enabled():
    try:
        c_iot = boto3.Session().client('iot')
        response = c_iot.get_indexing_configuration()

        logger.info('thingIndexingMode: {}'.format(response['thingIndexingConfiguration']['thingIndexingMode']))
        if response['thingIndexingConfiguration']['thingIndexingMode'] == 'OFF':
            return False

        return True
    except Exception as e:
        logger.error('{}'.format(e))
        raise Exception(e)


try:
    if not registry_indexing_enabled():
        raise Exception('registry indexing must be enabled for this program to work')

    search_things(100)

    logger.info('region: {} query_string: {}: NUM_THINGS: {}'.format(boto3.Session().region_name, args.query_string, NUM_THINGS))

except Exception as e:
    logger.error('{}'.format(e))
