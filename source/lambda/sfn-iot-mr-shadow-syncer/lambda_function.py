#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#
# shadow syncer
#
"""IoT DR: Lambda function
for syncing classic device shadows."""

import json
import logging
import os
import sys

import boto3

from botocore.config import Config
from dynamodb_json import json_util as ddb_json

logger = logging.getLogger()
for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
FORMAT = '%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)s - %(funcName)s - %(message)s'
h.setFormatter(logging.Formatter(FORMAT))
logger.addHandler(h)
logger.setLevel(logging.INFO)

ERRORS = []
IOT_ENDPOINT_PRIMARY = os.environ['IOT_ENDPOINT_PRIMARY']
IOT_ENDPOINT_SECONDARY = os.environ['IOT_ENDPOINT_SECONDARY']

class ShadowSyncerException(Exception): pass


def get_iot_data_endpoint(region, iot_endpoints):
    try:
        logger.info('region: {} iot_endpoints: {}'.format(region, iot_endpoints))
        iot_data_endpoint = None
        for endpoint in iot_endpoints:
            if region in endpoint:
                logger.info('region: {} in endpoint: {}'.format(region, endpoint))
                iot_data_endpoint = endpoint
                break

        if iot_data_endpoint is None:
            logger.info('iot_data_endpoint not found calling describe_endpoint')
            iot_data_endpoint = boto3.client('iot').describe_endpoint(endpointType='iot:Data-ATS')['endpointAddress']
            logger.info('iot_data_endpoint from describe_endpoint: {}'.format(iot_data_endpoint))
        else:
            logger.info('iot_data_endpoint from iot_endpoints: {}'.format(iot_data_endpoint))

        return iot_data_endpoint
    except Exception as e:
        logger.error('{}'.format(e))
        raise ShadowSyncerException(e)


def update_shadow(c_iot_data, thing_name, shadow):
    global ERRORS
    try:
        logger.info('update thing shadow: thing_name: {} payload: {}'.format(thing_name, shadow))

        response = c_iot_data.update_thing_shadow(
            thingName=thing_name,
            payload=json.dumps(shadow).encode()
        )

        logger.info('response: {}'.format(response))
    except Exception as e:
        logger.error('update_shadow: {}'.format(e))
        ERRORS.append('update_shadow: {}'.format(e))


def lambda_handler(event, context):
    global ERRORS
    logger.info('event: {}'.format(event))
    logger.debug('context: {}'.format(context))

    try:
        boto3_config = Config(retries = {'max_attempts': 12, 'mode': 'standard'})

        iot_data_endpoint = get_iot_data_endpoint(
            os.environ['AWS_REGION'],
            [IOT_ENDPOINT_PRIMARY, IOT_ENDPOINT_SECONDARY]
        )

        c_iot_data = boto3.client('iot-data', config=boto3_config, endpoint_url='https://{}'.format(iot_data_endpoint))

        event = ddb_json.loads(event)
        logger.info('cleaned event: {}'.format(event))
        if event['NewImage']['eventType'] == 'SHADOW_EVENT':
            thing_name = event['NewImage']['thing_name']
            shadow = {'state': event['NewImage']['state']}
            logger.info('thing_name: {} shadow: {}'.format(thing_name, shadow))

            update_shadow(c_iot_data, thing_name, shadow)
        else:
            logger.warn('eventType not a SHADOW_EVENT')

    except Exception as e:
        logger.error('{}'.format(e))
        ERRORS.append('lambda_handler: {}'.format(e))

    if ERRORS:
        error_message = ', '.join(ERRORS)
        logger.error('{}'.format(error_message))
        raise ShadowSyncerException('{}'.format(error_message))

    return {'message': 'shadow updated'}
