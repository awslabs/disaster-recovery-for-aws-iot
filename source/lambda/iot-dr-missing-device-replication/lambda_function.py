#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#
# missing device replication
#
"""IoT DR: replicate missing
devices from one region to another."""

import logging
import os
import time

import boto3

from boto3.dynamodb.conditions import Key
from device_replication import thing_exists, create_thing_with_cert_and_policy, delete_thing_create_error
from dynamodb_json import json_util as ddb_json

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DYNAMODB_ERROR_TABLE = os.environ['DYNAMODB_ERROR_TABLE']
SECONDARY_REGION = os.environ['AWS_REGION']

logger.info('DYNAMODB_ERROR_TABLE: {} SECONDARY_REGION: {}'.format(DYNAMODB_ERROR_TABLE, SECONDARY_REGION))

def post_provision_thing(c_iot, c_dynamo, item):
    try:
        start_time = int(time.time()*1000)
        thing_name = item['thing_name']
        primary_region = item['primary_region']
        logger.info('thing_name: {} primary_region: {}'.format(thing_name, primary_region))
        c_iot_p = boto3.client('iot', region_name = primary_region)

        # thing must exist in primary region
        if not thing_exists(c_iot_p, thing_name):
            logger.warn('thing_name "{}" does not exist in primary region: {}'.format(thing_name, primary_region))
            return 'thing_name "{}" does not exist in primary region {}'.format(thing_name, primary_region)

        logger.info('trying to post provision thing_name: {}'.format(thing_name))
        create_thing_with_cert_and_policy(c_iot, c_iot_p, thing_name, "", {}, primary_region, SECONDARY_REGION, 1, 0)

        delete_thing_create_error(c_dynamo, thing_name, DYNAMODB_ERROR_TABLE)

        end_time = int(time.time()*1000)
        duration = end_time - start_time
        logger.info('post_provision_thing duration: {}ms'.format(duration))
    except Exception as e:
        logger.error('post_provision_thing: {}'.format(e))


def find_orphaned_things(c_dynamo, c_dynamo_resource, c_iot):
    table = c_dynamo_resource.Table(DYNAMODB_ERROR_TABLE)
    while True:
        if not table.global_secondary_indexes or table.global_secondary_indexes[0]['IndexStatus'] != 'ACTIVE':
            print('Waiting for index to backfill...')
            time.sleep(5)
            table.reload()
        else:
            break

    response = table.query(
        # Add the name of the index you want to use in your query.
        IndexName="action-index",
        KeyConditionExpression=Key('action').eq('create-thing'),
    )
    logger.debug('response: {}'.format(response))

    for item in response['Items']:
        item = ddb_json.loads(item)
        logger.info('item: {}'.format(item))
        if 'primary_region' in item:
            post_provision_thing(c_iot, c_dynamo, item)
        else:
            logger.warn('cannot post provision device {} - primary region unknown'.format(item['thing_name']))


def lambda_handler(event, context):
    logger.info('event: {}'.format(event))

    c_dynamo = boto3.client('dynamodb')
    c_dynamo_resource = boto3.resource('dynamodb')
    c_iot = boto3.client('iot')
    find_orphaned_things(c_dynamo, c_dynamo_resource, c_iot)

    return True
