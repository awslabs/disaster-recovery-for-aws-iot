#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#
# thing crud
#
"""IoT DR: Lambda function to handle
thing CreateUpdateDelete"""

import logging
import os
import sys
import time

import boto3

import device_replication

from botocore.config import Config
from device_replication import (
    create_thing, create_thing_with_cert_and_policy,
    delete_thing_create_error, delete_thing,
    get_iot_data_endpoint
)
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
DYNAMODB_ERROR_TABLE = os.environ['DYNAMODB_ERROR_TABLE']
CREATE_MODE = os.environ.get('CREATE_MODE', 'complete')
IOT_ENDPOINT_PRIMARY = os.environ['IOT_ENDPOINT_PRIMARY']
IOT_ENDPOINT_SECONDARY = os.environ['IOT_ENDPOINT_SECONDARY']


class ThingCrudException(Exception): pass


def update_table_create_thing_error(c_dynamo, thing_name, primary_region, error_message):
    logger.info('update_table_create_thing_error: thing_name: {}'.format(thing_name))
    try:
        response = c_dynamo.update_item(
            TableName=DYNAMODB_ERROR_TABLE,
            Key={'thing_name': {'S': thing_name}, 'action': {'S': 'create-thing'}},
            AttributeUpdates={
                'primary_region': {'Value': {'S': primary_region}},
                'error_message': {'Value': {'S': error_message}},
                'time_stamp': {'Value': {'N': str(int(time.time()*1000))}}
            }
        )
        logger.info('update_table_create_thing_error: {}'.format(response))
    except Exception as e:
        logger.error("update_table_create_thing_error: {}".format(e))


def lambda_handler(event, context):
    global ERRORS
    ERRORS = []

    logger.info('event: {}'.format(event))

    try:
        event = ddb_json.loads(event)
        logger.info('cleaned event: {}'.format(event))

        boto3_config = Config(retries = {'max_attempts': 12, 'mode': 'standard'})

        c_iot = boto3.client('iot', config=boto3_config)
        c_dynamo = boto3.client('dynamodb')

        secondary_region = os.environ['AWS_REGION']
        logger.info('secondary_region: {}'.format(secondary_region))

        if event['NewImage']['operation'] == 'CREATED':
            logger.info('operation: {}'.format(event['NewImage']['operation']))
            thing_name = event['NewImage']['thingName']
            logger.info('thing_name: {}'.format(thing_name))
            attrs = {}
            if 'attributes' in event['NewImage'] and event['NewImage']['attributes']:
                attrs = {'attributes': {}}
                for key in event['NewImage']['attributes']:
                    attrs['attributes'][key] = event['NewImage']['attributes'][key]

            if 'attributes' in attrs:
                attrs['merge'] = False
            logger.info('attrs: {}'.format(attrs))

            thing_type_name = ""
            if 'thingTypeName' in event['NewImage']:
                thing_type_name = event['NewImage']['thingTypeName']
            logger.info('thing_type_name: {}'.format(thing_type_name))
            primary_region = event['NewImage']['aws:rep:updateregion']
            logger.info('primary_region: {}'.format(primary_region))
            logger.info('CREATE_MODE: {}'.format(CREATE_MODE))

            c_iot_p = boto3.client('iot', config=boto3_config, region_name = primary_region)

            start_time = int(time.time()*1000)
            if CREATE_MODE == 'thing_only':
                create_thing(c_iot, c_iot_p, thing_name, thing_type_name, attrs)
            else:
                create_thing_with_cert_and_policy(c_iot, c_iot_p, thing_name, thing_type_name, attrs, 3, 2)
            end_time = int(time.time()*1000)
            duration = end_time - start_time
            logger.info('thing created: thing_name: {}: duration: {}ms'.format(thing_name, duration))
            logger.info('thing created, deleting from dynamo if exists: thing_name: {}'.format(thing_name))
            delete_thing_create_error(c_dynamo, thing_name, DYNAMODB_ERROR_TABLE)

        if event['NewImage']['operation'] == 'UPDATED':
            logger.info('operation: {}'.format(event['NewImage']['operation']))
            thing_name = event['NewImage']['thingName']
            logger.info("thing_name: {}".format(thing_name))

            primary_region = event['NewImage']['aws:rep:updateregion']
            logger.info('primary_region: {}'.format(primary_region))

            c_iot_p = boto3.client('iot', config=boto3_config, region_name = primary_region)

            attrs = {}
            if 'attributes' in event['NewImage']:
                for key in event['NewImage']['attributes']:
                    attrs[key] = event['NewImage']['attributes'][key]

            merge = True
            if attrs:
                merge = False

            thing_type_name = ""
            if 'S' in event['NewImage']['thingTypeName']:
                thing_type_name = event['NewImage']['thingTypeName']['S']

            logger.info("thing_name: {} thing_type_name: {} attrs: {}".
                format(thing_name, thing_type_name, attrs))
            update_thing(c_iot, c_iot_p, thing_name, thing_type_name, attrs, merge)

        if event['NewImage']['operation'] == 'DELETED':
            logger.info('operation: {}'.format(event['NewImage']['operation']))
            thing_name = event['NewImage']['thingName']
            logger.info("thing_name: {}".format(thing_name))

            iot_data_endpoint = get_iot_data_endpoint(
                os.environ['AWS_REGION'],
                [IOT_ENDPOINT_PRIMARY, IOT_ENDPOINT_SECONDARY]
            )

            delete_thing(c_iot, thing_name, iot_data_endpoint)
            delete_thing_create_error(c_dynamo, thing_name, DYNAMODB_ERROR_TABLE)

    except device_replication.DeviceReplicationCreateThingException as e:
        logger.error(e)
        ERRORS.append("lambda_handler: {}".format(e))
        error_message = ', '.join(ERRORS)
        if event['NewImage']['operation'] == 'CREATED':
            update_table_create_thing_error(c_dynamo, thing_name, primary_region, error_message)

    except Exception as e:
        logger.error(e)
        ERRORS.append('lambda_handler: {}'.format(e))

    if ERRORS:
        error_message = ', '.join(ERRORS)
        logger.error('{}'.format(error_message))
        raise ThingCrudException('{}'.format(error_message))

    return {'message': 'success'}
