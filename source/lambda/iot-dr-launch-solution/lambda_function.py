#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#
# iot-dr-launch-solution
#

import json
import logging
import sys
import urllib.request
import uuid

from concurrent import futures
from datetime import datetime

import boto3

from botocore.exceptions import ClientError

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

MAX_WORKERS=6

REGION_TABLE = {
    "ap-northeast-1": 1,
    "ap-northeast-2": 1,
    "ap-southeast-1": 1,
    "ap-southeast-2": 1,
    "eu-central-1": 1,
    "eu-west-1": 1,
    "eu-west-2": 1,
    "us-east-1": 1,
    "us-east-2": 1,
    "us-west-1": 1,
    "us-west-2": 1
}


def cfnresponse_send(event, context, responseStatus, responseData, physicalResourceId=None, noEcho=False):
    logger.info("event: {}".format(event))
    logger.info("context: {}".format(context))

    responseUrl = event['ResponseURL']

    responseBody = {}
    responseBody['Status'] = responseStatus
    responseBody['Reason'] = 'See the details in CloudWatch Log Stream: {}'.format(context.log_stream_name)
    if 'Error' in responseData:
        responseBody['Reason'] = responseData['Error']
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


def stack_exists(stack_name, region):
    try:
        response = boto3.client('cloudformation', region_name=region).describe_stacks(
            StackName=stack_name)
        logger.info('response: {}'.format(response))
        return True
    except ClientError as e:
        logger.warn('stack does not exist: {}'.format(e))
        return False
    except Exception as e:
        logger.error('{}'.format(e))
        return False


def delete_cfn_stack(stack_name, region):
    try:
        if stack_exists(stack_name, region):
            c_cfn = boto3.client('cloudformation', region_name=region)
            logger.info('stack_name: {}'.format(stack_name))
            response = c_cfn.delete_stack(StackName=stack_name)
            logger.info('response: {}'.format(response))

            waiter = c_cfn.get_waiter('stack_delete_complete')
            logger.info('stack_name: {}: waiting for stack to be deleted'.format(stack_name))
            waiter.wait(StackName=stack_name, WaiterConfig={'Delay': 20, 'MaxAttempts': 36})
            logger.info('stack_name: {}: stack deleted'.format(stack_name))
        else:
            logger.warn('stack_name: {} does not exist in region: {}'.format(stack_name, region))
    except Exception as e:
        logger.error('{}'.format(e))


def empty_and_delete_bucket(bucket_name):
    try:
        session = boto3.Session()
        c_s3 = session.client('s3')
        s3 = session.resource(service_name='s3')
        bucket = s3.Bucket(bucket_name)
        response = bucket.object_versions.delete()
        logger.info('response: {}'.format(response))
        response = c_s3.delete_bucket(Bucket=bucket_name)
        logger.info('response: {}'.format(response))

    except c_s3.exceptions.NoSuchBucket as e:
        logger.warn('bucket {} does not exist: {}'.format(bucket_name, e))
    except Exception as e:
        logger.error('bucket_name: {}: {}'.format(bucket_name, e))


def verify_regions(primary_region, secondary_region):
    error = []

    if primary_region == secondary_region:
        msg = 'primary and secondary region may not be identical: primary_region: {} secondary_region: {}'.format(primary_region, secondary_region)
        logger.error(msg)
        raise Exception(msg)

    if not primary_region in REGION_TABLE:
        error.append('{} is not a valid AWS region'.format(primary_region))

    if not secondary_region in REGION_TABLE:
        error.append('{} is not a valid AWS region'.format(secondary_region))

    if error:
        msg = (', ').join(error)
        logger.error('{}'.format(msg))
        raise Exception('{}'.format(msg))


def verify_events_indexing_enabled(region):
    error = []
    try:
        client = boto3.client('iot', region_name=region)

        response = client.describe_event_configurations()
        logger.debug('response describe_event_configurations: {}'.format(response))
        logger.info('eventConfigurations: {}'.format(response['eventConfigurations']))

        events_not_enabled = []
        for event in ['THING', 'THING_GROUP', 'THING_GROUP_HIERARCHY', 'THING_GROUP_MEMBERSHIP', 'THING_TYPE', 'THING_TYPE_ASSOCIATION']:
            if response['eventConfigurations'][event]['Enabled'] == False:
                events_not_enabled.append(event)

        if events_not_enabled:
            error.append('IoT registry events for {} must be enabled'.format((', ').join(events_not_enabled)))

        response = client.get_indexing_configuration()
        logger.debug('response describe_event_configurations: {}'.format(response))
        logger.info('thingIndexingConfiguration.thingIndexingMode: {}'.format(response['thingIndexingConfiguration']['thingIndexingMode']))

        if not 'REGISTRY' in response['thingIndexingConfiguration']['thingIndexingMode']:
            error.append('registry indexing for things must be enabled, current setting is {}'.format(response['thingIndexingConfiguration']['thingIndexingMode']))

        if error:
            msg = (' - ').join(error)
            raise Exception('region: {}: {}'.format(region, msg))
        else:
            logger.info('region: {}: registry events and thing indexing enabled'.format(region))
    except Exception as e:
        logger.error('{}'.format(e))
        raise Exception('{}'.format(e))


def lambda_handler(event, context):
    logger.info('event: {}'.format(event))

    responseData = {}

    if event['RequestType'] == 'Update':
        logger.info('update cycle')
        responseData = {'Success': 'Update pass'}
        cfnresponse_send(event, context, SUCCESS, responseData, 'CustomResourcePhysicalID')

    if event['RequestType'] == 'Delete':
        cfn_result = FAILED
        responseData = {}
        logger.info('delete cycle')
        try:
            primary_region = event['ResourceProperties']['PRIMARY_REGION']
            secondary_region = event['ResourceProperties']['SECONDARY_REGION']
            lambda_arn = event['ServiceToken']
            logger.info('primary_region: {} secondary_region: {} ambda_arn: {}'.
                format(primary_region, secondary_region, lambda_arn))

            #verify_regions(primary_region, secondary_region)

            client = boto3.client('lambda')
            response = client.list_tags(
                Resource=lambda_arn
            )
            iot_dr_primary_stack_name = None
            iot_dr_secondary_stack_name = None
            iot_dr_r53_health_checker_name = None

            iot_dr_primary_bucket = None
            iot_dr_secondary_bucket = None

            executor = futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
            logger.info('executor: started: {}'.format(executor))

            if 'Tags' in response:
                if 'STACK_POSTFIX' in response['Tags']:
                    iot_dr_primary_stack_name = 'IoTDRPrimary{}'.format(response['Tags']['STACK_POSTFIX'])
                    executor.submit(delete_cfn_stack, iot_dr_primary_stack_name, primary_region)

                    iot_dr_secondary_stack_name = 'IoTDRSecondary{}'.format(response['Tags']['STACK_POSTFIX'])
                    executor.submit(delete_cfn_stack, iot_dr_secondary_stack_name, secondary_region)

                    iot_dr_r53_health_checker_name = 'R53HealthChecker{}'.format(response['Tags']['STACK_POSTFIX'])
                    executor.submit(delete_cfn_stack, iot_dr_r53_health_checker_name, primary_region)
                    executor.submit(delete_cfn_stack, iot_dr_r53_health_checker_name, secondary_region)

                if 'UUID' in response['Tags']:
                    iot_dr_primary_bucket = 'iot-dr-primary-{}'.format(response['Tags']['UUID'])
                    empty_and_delete_bucket(iot_dr_primary_bucket)

                    iot_dr_secondary_bucket = 'iot-dr-secondary-{}'.format(response['Tags']['UUID'])
                    empty_and_delete_bucket(iot_dr_secondary_bucket)


            logger.info('iot_dr_primary_stack_name: {} iot_dr_secondary_stack_name: {} iot_dr_r53_health_checker_name: {}'.
                format(iot_dr_primary_stack_name, iot_dr_secondary_stack_name, iot_dr_r53_health_checker_name))

            logger.info('iot_dr_primary_bucket: {} iot_dr_secondary_bucket: {}'.
                format(iot_dr_primary_bucket, iot_dr_secondary_bucket))

            logger.info('executor: waiting to finish')
            executor.shutdown(wait=True)
            logger.info('executor: shutted down')

            responseData = {'Success': 'resources deleted'}

            cfn_result = SUCCESS

        except Exception as e:
            cfn_result = FAILED
            responseData = {'Error': '{}: see also CloudWatch Log Stream: {}'.format(e, context.log_stream_name)}
            logger.error('{}'.format(e))

        cfnresponse_send(event, context, cfn_result, responseData, 'CustomResourcePhysicalID')

    if event['RequestType'] == 'Create':
        cfn_result = FAILED
        responseData = {}
        try:
            primary_region = event['ResourceProperties']['PRIMARY_REGION']
            secondary_region = event['ResourceProperties']['SECONDARY_REGION']
            codebuild_project = event['ResourceProperties']['CODEBUID_PROJECT']

            date_time = datetime.now().strftime('%Y%m%d%H%M%S')
            bucket_uuid = '{}'.format(uuid.uuid4())
            lambda_arn = event['ServiceToken']

            logger.info('primary_region: {} secondary_region: {} codebuild_project: {} date_time: {} bucket_uuid: {} lambda_arn: {}'.
                format(primary_region, secondary_region, codebuild_project, date_time, bucket_uuid, lambda_arn))

            verify_regions(primary_region, secondary_region)
            verify_events_indexing_enabled(primary_region)

            logger.info('tagging myself to preserve STACK_POSTFIX {} and UUID {}'.format(date_time, bucket_uuid))
            response = boto3.client('lambda').tag_resource(
                Resource=lambda_arn,
                Tags={
                    'STACK_POSTFIX': date_time,
                    'UUID': bucket_uuid
                }
            )
            logger.info('tag_resource: response: {}'.format(response))

            responseData['IOT_ENDPOINT_PRIMARY'] = boto3.client('iot', region_name=primary_region).describe_endpoint(endpointType='iot:Data-ATS')['endpointAddress']
            responseData['IOT_ENDPOINT_SECONDARY'] = boto3.client('iot', region_name=secondary_region).describe_endpoint(endpointType='iot:Data-ATS')['endpointAddress']

            responseData['STACK_POSTFIX'] = date_time
            responseData['UUID'] = bucket_uuid
            responseData['Success'] = 'Solution launch initiated'

            logger.info('starting codebuild_project {}'.format(codebuild_project))
            response = boto3.client('codebuild').start_build(
                projectName=codebuild_project,
                environmentVariablesOverride=[
                    {
                        'name': 'PRIMARY_REGION',
                        'value': primary_region,
                        'type': 'PLAINTEXT'
                    },
                    {
                        'name': 'SECONDARY_REGION',
                        'value': secondary_region,
                        'type': 'PLAINTEXT'
                    },
                    {
                        'name': 'STACK_POSTFIX',
                        'value': date_time,
                        'type': 'PLAINTEXT'
                    },
                    {
                        'name': 'UUID',
                        'value': bucket_uuid,
                        'type': 'PLAINTEXT'
                    }
                ]
            )
            logger.info('start_build: response: {}'.format(response))

            logger.info('responseData: {}'.format(responseData))

            cfn_result = SUCCESS

        except Exception as e:
            cfn_result = FAILED
            responseData = {'Error': '{}: see also CloudWatch Log Stream: {}'.format(e, context.log_stream_name)}
            logger.error('{}'.format(e))

        cfnresponse_send(event, context, cfn_result, responseData, 'CustomResourcePhysicalID')
