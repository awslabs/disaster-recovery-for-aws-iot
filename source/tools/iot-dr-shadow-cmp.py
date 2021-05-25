#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.

"""IoT DR: test shadow synchronisation
Shadows are created in the primary region
and are updated.
A get-shadow will be called in the secondary
region and the result will be compared to
the shadow content in the primary region.
After running the test shadows will be deleted."""

import argparse
import json
import logging
import random
import sys
import time
import uuid

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
parser.add_argument('--num-tests', default=10, type=int, help="Nunmber of tests to conduct.")
parser.add_argument('--max-workers', default=10, type=int, help="Maximum number of worker threads. Allowed maximum is 50.")
args = parser.parse_args()

NUM_SHADOWS_COMPARED = 0
NUM_SHADOWS_NOTSYNCED = 0
NUM_ERRORS = 0

THING_SHADOWS = {}


def update_shadow(i, c_iot_p):
    global THING_SHADOWS
    try:
        thing_name = '{}'.format(uuid.uuid4())
        i += 1
        shadow_payload = {'state':{'reported':{'temperature': '{}'.format(random.randrange(20, 40))}}}
        logger.info('i: {} thing_name: {} shadow_payload: {}'.format(i, thing_name, shadow_payload))

        response = c_iot_p.update_thing_shadow(
            thingName=thing_name,
            payload=json.dumps(shadow_payload)
        )
        logger.debug('response: {}'.format(response))
        logger.info('i: {} thing_name: {} response HTTPStatusCode: {}'.
            format(i, thing_name, response['ResponseMetadata']['HTTPStatusCode']))
        THING_SHADOWS[thing_name] = shadow_payload

    except Exception as e:
        logger.error('{}'.format(e))


def get_shadow(i, c_iot_s, thing_name):
    try:
        response = c_iot_s.get_thing_shadow(
            thingName=thing_name
        )
        logger.debug('response: {}'.format(response))
        payload = json.loads(response['payload'].read())
        logger.info('i: {} thing_name: {}: payload: {}'.format(i, thing_name, payload))
        return payload

    except c_iot_s.exceptions.ResourceNotFoundException:
        logger.warning('i: {} thing_name: {}: shadow does not exist'.format(i, thing_name))
        return {}
    except Exception as e:
        logger.error('replication: {}'.format(e))


def compare_shadow(i, c_iot_s, thing_name, shadow_payload):
    global NUM_SHADOWS_COMPARED, NUM_SHADOWS_NOTSYNCED, NUM_ERRORS
    try:
        logger.info('i: {} thing_name: {} shadow_payload: {}'.format(i, thing_name, shadow_payload))
        NUM_SHADOWS_COMPARED += 1
        shadow_payload_secondary = {}
        retries = 5
        wait = 2
        n = 1
        while not shadow_payload_secondary and n <= retries:
            logger.info('n: {}: get_shadow for thing_name: {}'.format(n, thing_name))
            n += 1
            shadow_payload_secondary = get_shadow(i, c_iot_s, thing_name)
            if not shadow_payload_secondary:
                retry_in = wait*n
                logger.info('n: {} thing_name: {}: no shadow payload, retrying in {} secs.'.format(n, thing_name, retry_in))
                time.sleep(retry_in)

        if not shadow_payload_secondary:
            logger.error('replication: thing_name: {}: shadow not replicated to secondary region'.format(thing_name))
            NUM_SHADOWS_NOTSYNCED += 1
            return

        logger.info('i: {} thing_name: {} shadow_payload: {} shadow_payload_secondary: {}'.format(i, thing_name, shadow_payload, shadow_payload_secondary))

        errors = []
        temperature = ""
        temperature_secondary = ""
        if 'temperature' in shadow_payload['state']['reported']:
            temperature = shadow_payload['state']['reported']['temperature']
        else:
            errors.append('thing_name: {} temperature not in shadow_payload'.format(thing_name))

        if 'temperature' in shadow_payload_secondary['state']['reported']:
            temperature_secondary = shadow_payload_secondary['state']['reported']['temperature']
        else:
            errors.append('thing_name: {}: temperature not in shadow_payload_secondary'.format(thing_name))

        if errors:
            logger.error('replication: {}'.format(errors))
            return

        logger.info('temperature: {} temperature_secondary: {}'.format(temperature, temperature_secondary))
        if temperature != temperature_secondary:
            logger.error('replication: thing_name: {} shadows missmatch: temperature: {} temperature_secondary: {}'.format(thing_name, temperature, temperature_secondary))
            return

        logger.info('i: {} thing_name: {} shadows match: temperature: {} temperature_secondary: {}'.format(i, thing_name, temperature, temperature_secondary))

    except Exception as e:
        logger.error('{}'.format(e))


def delete_shadow(i, c_iot_data, thing_name):
    try:
        region = c_iot_data.meta.region_name
        logger.info('i: {} thing_name: {} region: {}'.format(i, thing_name, region))
        response = c_iot_data.delete_thing_shadow(
            thingName=thing_name
        )
        logger.debug('response: {}'.format(response))
        logger.info('i: {} thing_name: {} region: {} response HTTPStatusCode: {}'.
            format(i, thing_name, region, response['ResponseMetadata']['HTTPStatusCode']))

    except c_iot_s.exceptions.ResourceNotFoundException:
        logger.warning('thing_name: {}: shadow does not exist'.format(thing_name))
        return {}
    except Exception as e:
        logger.error('replication: {}'.format(e))


try:
    logger.info('cmp: start')
    logger.info('primary_region: {} secondary_region: {} num_tests: {} max_workers: {}'.
        format(args.primary_region, args.secondary_region, args.num_tests, args.max_workers))
    time.sleep(2)

    NUM_SHADOWS_COMPARED = 0
    NUM_SHADOWS_NOTSYNCED = 0
    NUM_ERRORS = 0

    if args.max_workers > 50:
        logger.error('max allowed workers is 50 defined: {}'.format(args.max_workers))
        raise Exception('max allowed workers is 50 defined: {}'.format(args.max_workers))

    max_pool_connections = 10
    if args.max_workers >= 10:
        max_pool_connections = round(args.max_workers*1.2)

    logger.info('max_pool_connections: {}'.format(max_pool_connections))

    boto3_config = Config(
        max_pool_connections = max_pool_connections,
        retries = {'max_attempts': 10, 'mode': 'standard'}
    )

    session_p = boto3.Session(region_name=args.primary_region)
    session_s = boto3.Session(region_name=args.secondary_region)

    endpoint_p = session_p.client('iot').describe_endpoint(endpointType='iot:Data-ATS')['endpointAddress']
    endpoint_s = session_s.client('iot').describe_endpoint(endpointType='iot:Data-ATS')['endpointAddress']

    c_iot_p = session_p.client('iot-data', config=boto3_config, endpoint_url='https://{}'.format(endpoint_p))
    c_iot_s = session_s.client('iot-data', config=boto3_config, endpoint_url='https://{}'.format(endpoint_s))

    executor = futures.ThreadPoolExecutor(max_workers=args.max_workers)
    logger.info('executor update_shadow: started: {}'.format(executor))

    for x in range(args.num_tests):
        executor.submit(update_shadow, x, c_iot_p)

    logger.info('executor update_shadow: waiting to finish')
    executor.shutdown(wait=True)
    logger.info('executor update_shadow: shutted down')


    executor = futures.ThreadPoolExecutor(max_workers=args.max_workers)
    logger.info('executor compare_shadow: started: {}'.format(executor))

    logger.info(THING_SHADOWS)
    y = 0
    for thing_name in THING_SHADOWS.keys():
        y += 1
        executor.submit(compare_shadow, y, c_iot_s, thing_name, THING_SHADOWS[thing_name])

    logger.info('executor compare_shadow: waiting to finish')
    executor.shutdown(wait=True)
    logger.info('executor compare_shadow: shutted down')

    executor = futures.ThreadPoolExecutor(max_workers=args.max_workers)
    logger.info('executor delete_shadow: started: {}'.format(executor))
    z = 0
    for thing_name in THING_SHADOWS.keys():
        z += 1
        executor.submit(delete_shadow, z, c_iot_p, thing_name)
        executor.submit(delete_shadow, z, c_iot_s, thing_name)

    logger.info('executor delete_shadow: waiting to finish')
    executor.shutdown(wait=True)
    logger.info('executor delete_shadow: shutted down')

    logger.info('cmp: stats: NUM_SHADOWS_COMPARED: {} NUM_SHADOWS_NOTSYNCED: {} NUM_ERRORS: {}'.format(NUM_SHADOWS_COMPARED, NUM_SHADOWS_NOTSYNCED, NUM_ERRORS))

    logger.info('cmp: stop')
except Exception as e:
    logger.error('{}'.format(e))
