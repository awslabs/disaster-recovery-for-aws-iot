#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#
# iot-dr-create-r53-checker
#
"""IoT DR: Lambda function
to create an Amazon Route 53
health checker."""


import hashlib
import json
import logging
import os
import shutil
import random
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

S3_BUCKET = os.environ['S3_BUCKET']
ROOT_CA_URL = 'https://www.amazontrust.com/repository/AmazonRootCA1.pem'

SUCCESS = "SUCCESS"
FAILED = "FAILED"


def write_lambda_function(tmp_dir):
    function_code = """# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.

import json
import logging
import os
import sys
import threading
import time


from awscrt import io, mqtt, auth, http
from awsiot import mqtt_connection_builder
from datetime import datetime
from uuid import uuid4

logger = logging.getLogger()
for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
FORMAT = '%(asctime)s [%(levelname)s]: %(threadName)s:%(filename)s:%(funcName)s:%(lineno)s: %(message)s'
h.setFormatter(logging.Formatter(FORMAT))
logger.addHandler(h)
logger.setLevel(logging.INFO)
#logger.setLevel(logging.DEBUG)

CA = os.environ['CA']
CERT = os.environ['CERT']
CLIENT_ID = os.environ['CLIENT_ID']
COUNT = int(os.environ.get('COUNT', 2))
ENDPOINT = os.environ['ENDPOINT']
KEY = os.environ['KEY']
QUERY_STRING = os.environ['QUERY_STRING']
RECEIVE_TIMEOUT = float(os.environ.get('RECEIVE_TIMEOUT', 3))

#io.init_logging(getattr(io.LogLevel, 'Info'), 'stderr')
io.init_logging(getattr(io.LogLevel, 'NoLogs'), 'stderr')
RECEIVED_COUNT = 0
RECEIVED_ALL_EVENT = threading.Event()

# Callback when connection is accidentally lost.
def on_connection_interrupted(connection, error, **kwargs):
    logger.info("connection interrupted: error: {}".format(error))


# Callback when an interrupted connection is re-established.
def on_connection_resumed(connection, return_code, session_present, **kwargs):
    logger.info("connection resumed: return_code: {} session_present: {}".format(return_code, session_present))

    if return_code == mqtt.ConnectReturnCode.ACCEPTED and not session_present:
        logger.info("Session did not persist. Resubscribing to existing topics...")
        resubscribe_future, _ = connection.resubscribe_existing_topics()

        # Cannot synchronously wait for resubscribe result because we're on the connection's event-loop thread,
        # evaluate result with a callback instead.
        resubscribe_future.add_done_callback(on_resubscribe_complete)


def on_resubscribe_complete(resubscribe_future):
        resubscribe_results = resubscribe_future.result()
        logger.info("resubscribe results: {}".format(resubscribe_results))

        for topic, qos in resubscribe_results['topics']:
            if qos is None:
                sys.exit("Server rejected resubscribe to topic: {}".format(topic))


# Callback when the subscribed topic receives a message
def on_message_received(topic, payload, **kwargs):
    logger.info("message received: topic: {} payload: {}".format(topic, payload))
    global RECEIVED_COUNT
    RECEIVED_COUNT += 1
    if RECEIVED_COUNT == COUNT:
        RECEIVED_ALL_EVENT.set()

def lambda_handler(event, context):
    logger.info('r53-health-check: start')
    logger.info('event: {}'.format(event))

    try:
        if COUNT < 1:
            raise Exception('COUNT must be greate or equal 1: defined: {}'.format(COUNT))

        uuid = '{}'.format(uuid4())
        client_id = '{}-{}'.format(CLIENT_ID, uuid)
        topic = 'dr/r53/check/{}/{}'.format(CLIENT_ID, uuid)
        logger.info('client_id: {} topic: {}'.format(client_id, topic))

        if not 'queryStringParameters' in event:
            logger.error('queryStringParameters missing')
            return {
                'statusCode': 503,
                'body': json.dumps({ 'message': 'internal server error'})
            }

        if not 'hashme' in event['queryStringParameters']:
            logger.error('hashme missing')
            return {
                'statusCode': 503,
                'body': json.dumps({ 'message': 'internal server error'})
            }

        if event['queryStringParameters']['hashme'] != QUERY_STRING:
            logger.error('query string missmatch: rawQueryString: {}'.format(event['queryStringParameters']['hashme']))
            return {
                'statusCode': 503,
                'body': json.dumps({ 'message': 'internal server error'})
            }

        # Spin up resources
        event_loop_group = io.EventLoopGroup(1)
        host_resolver = io.DefaultHostResolver(event_loop_group)
        client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)

        mqtt_connection = mqtt_connection_builder.mtls_from_path(
            endpoint=ENDPOINT,
            cert_filepath=CERT,
            pri_key_filepath=KEY,
            client_bootstrap=client_bootstrap,
            ca_filepath=CA,
            on_connection_interrupted=on_connection_interrupted,
            on_connection_resumed=on_connection_resumed,
            client_id=client_id,
            clean_session=False,
            keep_alive_secs=6)

        logger.info("connecting: endpoint: {} client_id: {}".format(
            ENDPOINT, client_id))

        connect_future = mqtt_connection.connect()

        # Future.result() waits until a result is available
        connect_future.result()
        logger.info("connected to endpoint: {}".format(ENDPOINT))

        # Subscribe
        logger.info("subscribing: topic: {}".format(topic))
        subscribe_future, packet_id = mqtt_connection.subscribe(
            topic=topic,
            qos=mqtt.QoS.AT_LEAST_ONCE,
            callback=on_message_received)

        subscribe_result = subscribe_future.result()
        logger.info("subscribed: qos: {}".format(str(subscribe_result['qos'])))

        logger.info("sending {} message(s)".format(COUNT))

        publish_count = 1
        while (publish_count <= COUNT):
            message = {
                "message": "R53 health check",
                "count": "{}".format(publish_count),
                "datetime": "{}".format(datetime.now().isoformat())
            }

            if 'requestContext' in event and 'http' in event['requestContext'] and 'sourceIp' in event['requestContext']['http']:
                message['source_ip'] = {'source': 'http', 'ip': event['requestContext']['http']['sourceIp']}

            if 'requestContext' in event and 'identity' in event['requestContext'] and 'sourceIp' in event['requestContext']['identity']:
                message['source_ip'] = {'source': 'identity', 'ip': event['requestContext']['identity']['sourceIp']}

            logger.info("publishing: topic {}: message: {}".format(topic, message))
            mqtt_connection.publish(
                topic=topic,
                payload=json.dumps(message),
                qos=mqtt.QoS.AT_LEAST_ONCE)
            #time.sleep(1)
            publish_count += 1

        # Wait for all messages to be received.
        # This waits forever if count was set to 0.
        if not RECEIVED_ALL_EVENT.is_set():
            logger.info("waiting for all message(s) to be received: {}/{}".format(RECEIVED_COUNT, COUNT))

        if not RECEIVED_ALL_EVENT.wait(RECEIVE_TIMEOUT):
            raise Exception('not all message received after timeout: received: {} expected: {} timeout: {}'.format(
                RECEIVED_COUNT, COUNT, RECEIVE_TIMEOUT))

        logger.info("message(s) received: {}/{}".format(RECEIVED_COUNT, COUNT))

        # Disconnect
        logger.info("initiating disconnect")
        disconnect_future = mqtt_connection.disconnect()
        disconnect_future.result()
        logger.info("disconnected")
        logger.info('r53-health-check: finished: messages: published/received: {}/{}'.format(
            publish_count-1, RECEIVED_COUNT))

        return {
            'statusCode': 200,
            'body': json.dumps({ 'mqtt_status': 'healthy' })
        }
    except Exception as e:
        logger.error('r53-health-check: finished: with errror: {}'.format(e))
        return {
            'statusCode': 503,
            'body': json.dumps({ 'status': 'error'})
        }

if __name__ == '__main__':
    logger.info('calling lambda_handler')
    lambda_handler({"rawQueryString": QUERY_STRING}, None)

"""
    try:
        logger.info('writing lambda_function.py to tmp_dir: {}'.format(tmp_dir))
        f = open('{}/lambda_function.py'.format(tmp_dir), 'w')
        f.write(function_code)
        f.close()
    except Exception as e:
        logger.error('{}'.format(e))
        raise Exception(e)


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


def create_thing(tmp_dir, timestamp, account_id, region, responseData):
    try:
        thing_name = 'iot-dr-r53-checker-{}'.format(timestamp)
        policy_name = '{}_Policy'.format(thing_name)
        logger.info('thing_name: {} policy_name: {} region: {} account_id: {}'.format(thing_name, policy_name, region, account_id))

        policy_documet = {
              "Version": "2012-10-17",
              "Statement": [
                {
                  "Effect": "Allow",
                  "Action": [
                    "iot:Connect"
                  ],
                  "Resource": "*"
                },
                {
                  "Effect": "Allow",
                  "Action": [
                    "iot:Publish"
                  ],
                  "Resource": [
                    "arn:aws:iot:{}:{}:topic/dr/*".format(region, account_id)
                  ]
                },
                {
                  "Effect": "Allow",
                  "Action": [
                    "iot:Receive"
                  ],
                  "Resource": [
                    "arn:aws:iot:{}:{}:topic/dr/*".format(region, account_id)
                  ]
                },
                {
                  "Effect": "Allow",
                  "Action": [
                    "iot:Subscribe"
                  ],
                  "Resource": [
                    "arn:aws:iot:{}:{}:topicfilter/dr/*".format(region, account_id)
                  ]
                }
              ]
            }

        client = boto3.client('iot')

        response = client.create_policy(
            policyName=policy_name,
            policyDocument=json.dumps(policy_documet)
        )

        response = client.create_keys_and_certificate(setAsActive=True)
        certificate_arn = response['certificateArn']
        certificate_id = response['certificateId']
        logger.info('certificate_arn: {}, certificate_id: {}'.format(certificate_arn, certificate_id))

        cert_file = '{}.cert.pem'.format(thing_name)
        file_c = open('{}/{}'.format(tmp_dir, cert_file),'w')
        file_c.write(response['certificatePem'])
        file_c.close()
        responseData['CERT'] = cert_file

        key_file = '{}.private.key'.format(thing_name)
        file_k = open('{}/{}'.format(tmp_dir, key_file), 'w')
        file_k.write(response['keyPair']['PrivateKey'])
        file_k.close()
        responseData['KEY'] = key_file

        response = client.create_thing(thingName=thing_name)

        response = client.attach_policy(policyName=policy_name,target=certificate_arn)

        response = client.attach_thing_principal(thingName=thing_name, principal=certificate_arn)

    except Exception as e:
        logger.error('{}'.format(e))
        raise Exception(e)


def get_root_ca(tmp_dir):
    try:
        logger.info('get root CA from: {}'.format(ROOT_CA_URL))
        response = urllib.request.urlopen(ROOT_CA_URL)
        cert = response.read()

        f=open('{}/root.ca.pem'.format(tmp_dir), 'w')
        f.write(cert.decode())
        f.close()
    except Exception as e:
        logger.error('{}'.format(e))
        raise Exception(e)


def lambda_handler(event, context):
    logger.info('event: {}'.format(event))

    responseData = {}

    if event['RequestType'] == 'Update':
        logger.info('nothing to do in update cycle')
        responseData = {'Success': 'Update pass'}
        cfnresponse_send(event, context, SUCCESS, responseData, 'CustomResourcePhysicalID')

    if event['RequestType'] == 'Delete':
        logger.info('nothing to do in delete cycle')
        responseData = {'Success': 'Delete pass'}
        cfnresponse_send(event, context, SUCCESS, responseData, 'CustomResourcePhysicalID')

    if event['RequestType'] == 'Create':
        cfn_result = FAILED
        responseData = {}
        try:
            account_id = event['ResourceProperties']['ACCOUNT_ID']
            region = event['ResourceProperties']['REGION']
            timestamp = datetime.now().strftime('%Y%m%d%H%M%S')

            tmp_dir = '/tmp/{}'.format(timestamp)
            os.makedirs(tmp_dir, mode=0o755)

            write_lambda_function(tmp_dir)
            get_root_ca(tmp_dir)
            create_thing(tmp_dir, timestamp, account_id, region, responseData)
            rc = os.system('pip install awsiotsdk -q --no-cache-dir -t {}'.format(tmp_dir))
            logger.info('rc: {}'.format(rc))

            zip_file = shutil.make_archive('/tmp/iot-dr-r53-checker', 'zip', tmp_dir)
            logger.info('zip_file: {}'.format(zip_file))

            logger.info('uploading file: {} to s3 bucket: {}'.format(zip_file, S3_BUCKET))
            s3 = boto3.resource('s3')
            s3.meta.client.upload_file(zip_file, S3_BUCKET, zip_file.split('/')[-1])

            endpoint = boto3.client('iot').describe_endpoint(endpointType='iot:Data-ATS')['endpointAddress']
            responseData['ENDPOINT'] = endpoint

            r=random.random();
            query_string = hashlib.sha256(bytes(str(r).encode())).hexdigest()
            logger.info('endpoint: {} query_string: {}'.format(endpoint, query_string))
            responseData['QUERY_STRING'] = query_string

            responseData['CA'] = 'root.ca.pem'
            responseData['CLIENT_ID'] = 'r53-checker'
            responseData['Success'] = 'R53 health checker lambda created'

            logger.info('responseData: {}'.format(responseData))

            cfn_result = SUCCESS

        except Exception as e:
          logger.error('{}'.format(e))
          raise Exception(e)

        cfnresponse_send(event, context, cfn_result, responseData, 'CustomResourcePhysicalID')
