#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.

"""IoT DR: compare device
configuration in primary and
secondary region."""

import argparse
import json
import logging
import sys
import time
import traceback

from concurrent import futures

import boto3
import boto3.session

from botocore.config import Config


logger = logging.getLogger()
for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
FORMAT = '%(asctime)s [%(levelname)s]: %(threadName)s-%(filename)s:%(lineno)s-%(funcName)s: %(message)s'
h.setFormatter(logging.Formatter(FORMAT))
logger.addHandler(h)
logger.setLevel(logging.INFO)
#logger.setLevel(logging.DEBUG)

parser = argparse.ArgumentParser(description="Compare device configuration in two regions")
parser.add_argument('--primary-region', required=True, help="Primary aws region.")
parser.add_argument('--secondary-region', required=True, help="Secondary aws region.")
parser.add_argument('--max-workers', default=10, type=int, help="Maximum number of worker threads. Allowed maximum is 50.")
parser.add_argument('--query-string', default='thingName:*', help="Query string.")
args = parser.parse_args()

NUM_THINGS_COMPARED = 0
NUM_THINGS_NOTSYNCED = 0
NUM_ERRORS = 0


def print_response(response):
    del response['ResponseMetadata']
    print(json.dumps(response, indent=2, default=str))


def get_device_status(c_iot, thing_name):
    logger.info('thing_name: {}'.format(thing_name))

    try:
        device_status = {thing_name: {'policy': '', 'cert_id': ''}}
        response = c_iot.describe_thing(thingName=thing_name)
        logger.debug('response: {}'.format(response))
        logger.info('exists: thing_name: {}'.format(thing_name))

        response = c_iot.list_thing_principals(thingName=thing_name)

        for principal in response['principals']:
            #print('PRINCIPAL: {}'.format(principal))
            cert_id = principal.split('/')[-1]
            device_status[thing_name]['cert_id'] = cert_id
            response = c_iot.describe_certificate(certificateId=principal.split('/')[-1])

            response = c_iot.list_principal_policies(principal=principal)
            #print('POLICIES')

            for policy in response['policies']:
                response = c_iot.get_policy(policyName=policy['policyName'])
                device_status[thing_name]['policy'] = policy['policyName']

        return device_status

    except c_iot.exceptions.ResourceNotFoundException:
        logger.info('replication error: thing does not exist: thing_name: {}'.format(thing_name))
        return {}

    except Exception as e:
        logger.error('{}'.format(e))
        raise Exception(e)



def compare_device(thing_name):
    global NUM_THINGS_COMPARED, NUM_THINGS_NOTSYNCED, NUM_ERRORS
    try:
        logger.info('thing_name: {}'.format(thing_name))
        start_time = int(time.time()*1000)
        device_status_primary = get_device_status(c_iot_p, thing_name)
        device_status_secondary = get_device_status(c_iot_s, thing_name)
        logger.info('thing_name: {} device_status_primary: {} device_status_secondary: {}'.format(thing_name, device_status_primary, device_status_secondary))

        errors = []
        if not thing_name in device_status_primary:
            errors.append('thing name does not exist in primary')
        elif not thing_name in device_status_secondary:
            errors.append('thing name does not exist in secondary')

        if thing_name in device_status_primary and thing_name in device_status_secondary:
            if device_status_primary[thing_name]['cert_id'] != device_status_secondary[thing_name]['cert_id']:
                errors.append('cert id missmatch')
            if device_status_primary[thing_name]['policy'] != device_status_secondary[thing_name]['policy']:
                errors.append('policy missmatch')

        if errors:
            logger.error('replication error: {}: primary: {} secondary: {}'.format(','.join(errors), device_status_primary, device_status_secondary))
            NUM_ERRORS += 1

        end_time = int(time.time()*1000)
        duration = end_time - start_time
        NUM_THINGS_COMPARED += 1
        logger.info('compare device: thing_name: {} duration: {}ms'.format(thing_name, duration))
    except Exception as e:
        logger.error('{}'.format(e))
        NUM_ERRORS += 1
        traceback.print_stack()


def get_next_token(response):
    next_token = None
    if 'nextToken' in response:
        next_token = response['nextToken']

    return next_token


def get_search_things(query_string, max_results):
    logger.info('query_string: {} max_results: {}'.format(query_string, max_results))
    try:
        response = c_iot_p.search_index(
            indexName='AWS_Things',
            queryString=query_string,
            maxResults=max_results
        )

        for thing in response['things']:
            executor.submit(compare_device, thing['thingName'])

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
                executor.submit(compare_device, thing['thingName'])
    except Exception as e:
        logger.error('{}'.format(e))


def registry_indexing_enabled():
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


try:
    logger.info('cmp: start')
    logger.info('primary_region: {} secondary_region: {} query_string: {} max_workers: {}'.
        format(args.primary_region, args.secondary_region, args.query_string, args.max_workers))
    time.sleep(2)

    NUM_THINGS_COMPARED = 0
    NUM_THINGS_NOTSYNCED = 0
    NUM_ERRORS = 0

    if args.max_workers > 50:
        logger.error('max allowed workers is 50 defined: {}'.format(args.max_workers))
        raise Exception('max allowed workers is 50 defined: {}'.format(args.max_workers))

    MAX_POOL_CONNECTIONS = 10
    if args.max_workers >= 10:
        MAX_POOL_CONNECTIONS = round(args.max_workers*1.2)

    logger.info('MAX_POOL_CONNECTIONS: {}'.format(MAX_POOL_CONNECTIONS))

    boto3_config = Config(
        max_pool_connections = MAX_POOL_CONNECTIONS,
        retries = {'max_attempts': 10, 'mode': 'standard'}
    )

    session_p = boto3.Session(region_name=args.primary_region)
    session_s = boto3.Session(region_name=args.secondary_region)
    c_iot_p = session_p.client('iot', config=boto3_config)
    c_iot_s = session_s.client('iot', config=boto3_config)

    executor = futures.ThreadPoolExecutor(max_workers=args.max_workers)
    logger.info('executor: started: {}'.format(executor))

    if not registry_indexing_enabled():
        logger.info('registry indexing enabled must be enabled in region: {}'.format(args.primary_region))
        raise Exception('indexing not enabled in region: {}'.format(args.primary_region))

    get_search_things(args.query_string, 100)


    logger.info('executor: waiting to finish')
    executor.shutdown(wait=True)
    logger.info('executor: shutted down')

    logger.info('cmp: stats: NUM_THINGS_COMPARED: {} NUM_THINGS_NOTSYNCED: {} NUM_ERRORS: {}'.format(NUM_THINGS_COMPARED, NUM_THINGS_NOTSYNCED, NUM_ERRORS))

    logger.info('cmp: stop')
except Exception as e:
    logger.error('{}'.format(e))
