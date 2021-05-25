#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import json
import logging
import os
import sys
import threading

from datetime import datetime
from uuid import uuid4

from awscrt import io, mqtt
from awsiot import mqtt_connection_builder

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
            'body': json.dumps({ 'mqtt_status': 'unhealthy', 'error': '{}'.format(e)})
        }

if __name__ == '__main__':
    logger.info('calling lambda_handler')
    lambda_handler({"rawQueryString": QUERY_STRING}, None)
