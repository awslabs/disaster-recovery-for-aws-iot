#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import json
import logging
import sys
import urllib.request

from datetime import datetime

import boto3

logger = logging.getLogger()
for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
FORMAT = '%(asctime)s [%(levelname)s]: %(threadName)s-%(filename)s:%(lineno)s-%(funcName)s: %(message)s'
h.setFormatter(logging.Formatter(FORMAT))
logger.addHandler(h)
logger.setLevel(logging.INFO)


SUCCESS = "SUCCESS"
FAILED = "FAILED"


def cfnresponse_send(event, context, responseStatus, responseData, physicalResourceId=None, noEcho=False):
    logger.info("event: {}".format(event))
    logger.info("context: {}".format(context))

    responseUrl = event['ResponseURL']

    responseBody = {}
    responseBody['Status'] = responseStatus
    responseBody['Reason'] = 'See the details in CloudWatch Log Stream: {}'.format(context.log_stream_name)
    responseBody['PhysicalResourceId'] = physicalResourceId or context.log_stream_name
    responseBody['StackId'] = event['StackId']
    responseBody['RequestId'] = event['RequestId']
    responseBody['LogicalResourceId'] = event['LogicalResourceId']
    responseBody['NoEcho'] = noEcho
    responseBody['Data'] = responseData

    json_responseBody = json.dumps(responseBody)

    logger.info("Response body: {}\n".format(json_responseBody))

    headers = {
        'content-type' : '',
        'content-length' : str(len(json_responseBody))
    }

    logger.info("responseUrl: {}".format(responseUrl))
    try:
        req = urllib.request.Request(url=responseUrl,
                                     data=json_responseBody.encode(),
                                     headers=headers,
                                     method='PUT')
        with urllib.request.urlopen(req) as f:
            pass
        logger.info("urllib request: req: {} status: {} reason: {}".format(req, f.status, f.reason))

    except Exception as e:
        logger.error("urllib request: {}".format(e))


def lambda_handler(event, context):
    logger.info('event: {}'.format(event))

    responseData = {}

    if event['RequestType'] == 'Update':
        logger.info('update cycle')
        responseData = {'Success': 'Update pass'}
        cfnresponse_send(event, context, SUCCESS, responseData, 'CustomResourcePhysicalID')

    if event['RequestType'] == 'Delete':
        logger.info('delete cycle')
        client = boto3.client('lambda')
        response = client.list_tags(
            Resource=event['ServiceToken']
        )
        if 'Tags' in response and 'STACK_POSTFIX' in response['Tags']:
            iot_dr_primary_stack_name = 'IoTDRPrimary{}'.format(response['Tags']['STACK_POSTFIX'])
            logger.info('iot_dr_primary_stack_name: {}'.format(iot_dr_primary_stack_name))
        else:
            logger.warn('no tag with name STACK_POSTFIX: delete stacks manually')

        responseData = {'Success': 'Delete pass'}
        cfnresponse_send(event, context, SUCCESS, responseData, 'CustomResourcePhysicalID')

    if event['RequestType'] == 'Create':
        cfn_result = FAILED
        responseData = {}
        try:
            primary_region = event['ResourceProperties']['PRIMARY_REGION']
            secondary_region = event['ResourceProperties']['SECONDARY_REGION']
            date_time = datetime.now().strftime('%Y%m%d%H%M%S')

            logger.info('primary_region: {} secondary_region: {} date_time: {}'.
                format(primary_region, secondary_region, date_time))

            lambda_arn = event['ServiceToken']
            logger.info('lambda_arn: {}'.format(lambda_arn))

            client = boto3.client('lambda')
            response = client.tag_resource(
                Resource=lambda_arn,
                Tags={
                    'STACK_POSTFIX': date_time
                }
            )

            responseData['STACK_POSTFIX'] = date_time
            responseData['Success'] = 'Solution launch initiated'

            logger.info('responseData: {}'.format(responseData))

            cfn_result = SUCCESS

        except Exception as e:
          logger.error('{}'.format(e))
          raise Exception(e)

        cfnresponse_send(event, context, cfn_result, responseData, 'CustomResourcePhysicalID')
