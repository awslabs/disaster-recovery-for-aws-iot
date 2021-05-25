#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#
# dynamodb trigger function
#

import boto3
import json
import logging
import os
import sys

logger = logging.getLogger()
for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
FORMAT = '%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)s - %(funcName)s - %(message)s'
h.setFormatter(logging.Formatter(FORMAT))
logger.addHandler(h)
logger.setLevel(logging.INFO)

logger.debug('boto3 version: {}'.format(boto3.__version__))

STATEMACHINE_ARN = os.environ['STATEMACHINE_ARN']

c_sfn = boto3.client('stepfunctions')

def lambda_handler(event, context):
    logger.info('event: {}'.format(event))
    logger.debug(json.dumps(event, indent=4))

    try:
        logger.info('length Records: {}'.format(len(event['Records'])))

        for record in event['Records']:
            logger.info('event type: {}'.format(record['dynamodb']['NewImage']['eventType']['S']))
            item = record['dynamodb']
            logger.info('item: {}'.format(item))
            logger.info('event type: {}'.format(item['NewImage']['eventType']['S']))
            logger.info('region: {} update region: {}'.format(os.environ['AWS_REGION'], item['NewImage']['aws:rep:updateregion']['S']))

            if os.environ['AWS_REGION'] == item['NewImage']['aws:rep:updateregion']['S']:
                logger.info('item has been created in the same region and is not to be considered as replication - ignoring')
                return {'message': 'item has been created in the same region and is not to be considered as replication - ignoring'}

            input = json.dumps(item)
            logger.debug(input)

            logger.info('starting statemachine execution: STATEMACHINE_ARN: {}'.format(STATEMACHINE_ARN))
            response = c_sfn.start_execution(
                stateMachineArn=STATEMACHINE_ARN,
                input=input
            )
            logger.info('response: {}'.format(response))

        return {'message': 'statemachine started'}
    except Exception as e:
        logger.error('{}'.format(e))
        return {'message': 'error: {}'.format(e)}
