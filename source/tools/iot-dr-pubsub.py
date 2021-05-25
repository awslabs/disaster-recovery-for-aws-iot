#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.

import argparse
import json
import logging
import sys
import threading
import time

import dns.resolver

from awscrt import io, mqtt, auth, http
from awsiot import mqtt_connection_builder
from datetime import datetime
from uuid import uuid4

logger = logging.getLogger()
for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
FORMAT = '%(asctime)s [%(levelname)s]: %(threadName)s-%(filename)s:%(lineno)s-%(funcName)s: %(message)s'
h.setFormatter(logging.Formatter(FORMAT))
logger.addHandler(h)
logger.setLevel(logging.INFO)

T = None
MQTT_CONNECTION = None

# This sample uses the Message Broker for AWS IoT to send and receive messages
# through an MQTT connection. On startup, the device connects to the server,
# subscribes to a topic, and begins publishing messages to that topic.
# The device should receive those same messages back from the message broker,
# since it is subscribed to that same topic.

parser = argparse.ArgumentParser(description="Send and receive messages through and MQTT connection.")
parser.add_argument('--endpoint', required=True, help="Your AWS IoT custom endpoint, not including a port. " +
                                                      "Ex: \"abcd123456wxyz-ats.iot.us-east-1.amazonaws.com\"")
parser.add_argument('--cert', help="File path to your client certificate, in PEM format.")
parser.add_argument('--key', help="File path to your private key, in PEM format.")
parser.add_argument('--root-ca', help="File path to root certificate authority, in PEM format. " +
                                      "Necessary if MQTT server uses a certificate that's not already in " +
                                      "your trust store.")
parser.add_argument('--client-id', default="test-" + str(uuid4()), help="Client ID for MQTT connection.")
parser.add_argument('--topic', default="test/topic", help="Topic to subscribe to, and publish messages to.")
parser.add_argument('--message', default="Hello World!", help="Message to publish. " +
                                                              "Specify empty string to publish nothing.")
parser.add_argument('--count', default=10, type=int, help="Number of messages to publish/receive before exiting. " +
                                                          "Specify 0 to run forever.")
parser.add_argument('--interval', default=10, type=int, help="Interval in seconds between publish requests.")                                                          
parser.add_argument('--use-websocket', default=False, action='store_true',
    help="To use a websocket instead of raw mqtt. If you " +
    "specify this option you must specify a region for signing, you can also enable proxy mode.")
parser.add_argument('--use-cname', default=False, action='store_true',
    help="Use CNAME resolution to connect to an endpoint.")
parser.add_argument('--use-custom-domain', default=False, action='store_true',
    help="Use a custom domain endpoint.")
parser.add_argument('--dr-mode', default=False, action='store_true',
    help="Use IoT DR mode. In DR mode the CNAME for the iot endpoint will be verified regularly.")
parser.add_argument('--signing-region', default='us-east-1', help="If you specify --use-web-socket, this " +
    "is the region that will be used for computing the Sigv4 signature")
parser.add_argument('--proxy-host', help="Hostname for proxy to connect to. Note: if you use this feature, " +
    "you will likely need to set --root-ca to the ca for your proxy.")
parser.add_argument('--proxy-port', type=int, default=8080, help="Port for proxy to connect to.")
parser.add_argument('--verbosity', choices=[x.name for x in io.LogLevel], default=io.LogLevel.NoLogs.name,
    help='Logging level')

# Using globals to simplify sample code
args = parser.parse_args()

io.init_logging(getattr(io.LogLevel, args.verbosity), 'stderr')

received_count = 0
received_all_event = threading.Event()

# Callback when connection is accidentally lost.
def on_connection_interrupted(connection, error, **kwargs):
    logger.info("Connection interrupted. error: {}".format(error))


# Callback when an interrupted connection is re-established.
def on_connection_resumed(connection, return_code, session_present, **kwargs):
    logger.info("Connection resumed. return_code: %s session_present: %s", 
        return_code, session_present)

    if return_code == mqtt.ConnectReturnCode.ACCEPTED and not session_present:
        logger.info("Session did not persist. Resubscribing to existing topics...")
        resubscribe_future, _ = connection.resubscribe_existing_topics()

        # Cannot synchronously wait for resubscribe result because we're on the connection's event-loop thread,
        # evaluate result with a callback instead.
        resubscribe_future.add_done_callback(on_resubscribe_complete)


def on_resubscribe_complete(resubscribe_future):
        resubscribe_results = resubscribe_future.result()
        logger.info("Resubscribe results: %s", resubscribe_results)

        for topic, qos in resubscribe_results['topics']:
            if qos is None:
                sys.exit("Server rejected resubscribe to topic: {}".format(topic))


# Callback when the subscribed topic receives a message
def on_message_received(topic, payload, **kwargs):
    logger.info("Received message from topic '%s': %s", topic, payload)
    global received_count
    received_count += 1
    if received_count == args.count:
        received_all_event.set()
        
        
def resolve_cname(cname):
    try:
        answers = dns.resolver.resolve(cname, 'CNAME')
        host = answers[0].to_text().rstrip('.')
        logger.info('query: %s host: %s num answers: %s',
            answers.qname, host, len(answers))
        return host
    except Exception as resolve_error:
        logger.error(resolve_error)
        return None


def resolve_txt(cname):
    try:
        answers = dns.resolver.resolve('_{}'.format(cname), 'TXT')
        logger.info('query qname: %s num answers: %s',
            answers.qname, len(answers))
        txt = json.loads(json.loads(answers[0].to_text()))
        logger.info('answer: %s txt: %s', answers[0].to_text(), txt)
        return txt
    except Exception as resolve_txt_error:
        logger.warning(resolve_txt_error)
        return {}

    
def dr_endpoint_verifier(current_iot_endpoint, cname):
    global MQTT_CONNECTION, T
    logger.info('running in dr-mode/cname: current_iot_endpoint: %s MQTT_CONNECTION: %s T: %s',
        current_iot_endpoint, MQTT_CONNECTION, T)

    iot_endpoint = resolve_cname(cname)
    logger.info('current_iot_endpoint: %s iot_endpoint: %s',
        current_iot_endpoint, iot_endpoint)

    if current_iot_endpoint != iot_endpoint:
        logger.info('REGION FAILOVER detected: %s -> %s',current_iot_endpoint, iot_endpoint)
        current_iot_endpoint = iot_endpoint
        logger.info('teminating current MQTT_CONNECTION')
        disconnect_future = MQTT_CONNECTION.disconnect()
        logger.info('disconnect_future result: %s', disconnect_future)
        disconnect_future.result()
        MQTT_CONNECTION = None
        logger.info('initiating new MQTT_CONNECTION to iot_endpoint: %s', iot_endpoint)
        connection_start(iot_endpoint)
        
    txt = resolve_txt(cname)
    if 'primary' in txt and txt['primary'] == current_iot_endpoint.split('.')[2]:
        logger.info('PRIMARY region')
    elif 'secondary' in txt and txt['secondary'] == current_iot_endpoint.split('.')[2]:
        logger.info('SECONDARY region')
    else:
        logger.warning('unable to determine primary/secondary region - no TXT entry')
    
    T = threading.Timer(60, dr_endpoint_verifier, [current_iot_endpoint, cname])
    T.start()


def dr_custom_endpoint_verifier(current_iot_endpoint, custom_endpoint):
    global MQTT_CONNECTION, T
    logger.info('running in dr-mode/custom_endpoint: current_iot_endpoint: %s MQTT_CONNECTION: %s T: %s',
        current_iot_endpoint, MQTT_CONNECTION, T)

    iot_endpoint = resolve_cname(custom_endpoint)
    logger.info('custom_endpoint: %s current_iot_endpoint: %s iot_endpoint: %s',
            custom_endpoint, current_iot_endpoint, iot_endpoint) 

    if current_iot_endpoint != iot_endpoint:
        logger.info('REGION FAILOVER detected: custom_endpoint: %s: %s -> %s',
                custom_endpoint, current_iot_endpoint, iot_endpoint)

        current_iot_endpoint = iot_endpoint
        logger.info('teminating current MQTT_CONNECTION')
        disconnect_future = MQTT_CONNECTION.disconnect()
        logger.info('disconnect_future result: %s', disconnect_future)
        disconnect_future.result()
        MQTT_CONNECTION = None
        logger.info('initiating new MQTT_CONNECTION to custom_endpoint: %s (%s)',
                custom_endpoint, iot_endpoint)
        connection_start(custom_endpoint)
        
    txt = resolve_txt(custom_endpoint)
    if 'primary' in txt and txt['primary'] == current_iot_endpoint.split('.')[2]:
        logger.info('PRIMARY region')
    elif 'secondary' in txt and txt['secondary'] == current_iot_endpoint.split('.')[2]:
        logger.info('SECONDARY region')
    else:
        logger.warning('unable to determine primary/secondary region')
    
    T = threading.Timer(60, dr_custom_endpoint_verifier, [current_iot_endpoint, custom_endpoint])
    T.start()


def connection_start(iot_endpoint):
    global MQTT_CONNECTION
    # Spin up resources
    event_loop_group = io.EventLoopGroup(1)
    host_resolver = io.DefaultHostResolver(event_loop_group)
    client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)

    if args.use_websocket == True:
        proxy_options = None
        if (args.proxy_host):
            proxy_options = http.HttpProxyOptions(host_name=args.proxy_host, port=args.proxy_port)

        credentials_provider = auth.AwsCredentialsProvider.new_default_chain(client_bootstrap)
        MQTT_CONNECTION = mqtt_connection_builder.websockets_with_default_aws_signing(
            endpoint=iot_endpoint,
            client_bootstrap=client_bootstrap,
            region=args.signing_region,
            credentials_provider=credentials_provider,
            websocket_proxy_options=proxy_options,
            ca_filepath=args.root_ca,
            on_connection_interrupted=on_connection_interrupted,
            on_connection_resumed=on_connection_resumed,
            client_id=args.client_id,
            clean_session=False,
            keep_alive_secs=6)

    else:
        MQTT_CONNECTION = mqtt_connection_builder.mtls_from_path(
            endpoint=iot_endpoint,
            cert_filepath=args.cert,
            pri_key_filepath=args.key,
            client_bootstrap=client_bootstrap,
            ca_filepath=args.root_ca,
            on_connection_interrupted=on_connection_interrupted,
            on_connection_resumed=on_connection_resumed,
            client_id=args.client_id,
            clean_session=True,
            keep_alive_secs=6)

    logger.info("Connecting to %s with client ID '%s'...",
        iot_endpoint, args.client_id)

    connect_future = MQTT_CONNECTION.connect()

    # Future.result() waits until a result is available
    connect_future.result()
    logger.info("Connected!")

    # Subscribe
    logger.info("Subscribing to topic '%s'", args.topic)
    subscribe_future, packet_id = MQTT_CONNECTION.subscribe(
        topic=args.topic,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=on_message_received)

    subscribe_result = subscribe_future.result()
    logger.info("Subscribed with %s", subscribe_result['qos'])


if __name__ == '__main__':
    if args.dr_mode == True and args.use_cname == False and args.use_custom_domain == False:
        logger.error('--dr-mode requires either --use-custom-domain or --use-cname, exiting')
        sys.exit(1)
        
    if args.use_cname == True and args.use_custom_domain == True:
        logger.error('--use-custom-domain and --use-cname are mutual exclusive, exiting')
        sys.exit(1)
    
    iot_endpoint = args.endpoint
    
    if args.use_cname == True:
        iot_endpoint = resolve_cname(args.endpoint)
    
    logger.info('iot_endpoint: %s', iot_endpoint)
    connection_start(iot_endpoint)
    
    if args.dr_mode == True:
        if args.use_cname == True:
            logger.info('starting dr_endpoint_verifier thread')
            T = threading.Timer(0, dr_endpoint_verifier, [iot_endpoint, args.endpoint])
            T.start()
        if args.use_custom_domain == True:
            logger.info('starting dr_custom_endpoint_verifier thread')
            iot_endpoint = resolve_cname(args.endpoint)
            T = threading.Timer(0, dr_custom_endpoint_verifier, [iot_endpoint, args.endpoint])
            T.start()
        
    # Publish message to server desired number of times.
    # This step is skipped if message is blank.
    # This step loops forever if count was set to 0.
    if args.message:
        if args.count == 0:
            print ("Sending messages until program killed")
        else:
            print ("Sending {} message(s)".format(args.count))

        publish_count = 1
        while (publish_count <= args.count) or (args.count == 0):
            if not MQTT_CONNECTION:
                logger.warning('no active MQTT_CONNECTION will skip this publish cycle')
                continue
            
            message = {
                "message": "IoT DR test",
                "client_id": args.client_id,
                "count": "{}".format(publish_count),
                "datetime": "{}".format(datetime.now().isoformat())
            }
            logger.info('publish: topic: %s message: %s', args.topic, message)
            MQTT_CONNECTION.publish(
                topic=args.topic,
                payload=json.dumps(message),
                qos=mqtt.QoS.AT_LEAST_ONCE)
            time.sleep(args.interval)
            publish_count += 1
            
            logger.info('T: %s', T)
            if args.dr_mode == True and not T.is_alive():
                logger.warning('dr_endpoint_verifier thread not alive, restarting')
                iot_endpoint = resolve_cname(args.endpoint)
                T = threading.Timer(0, dr_endpoint_verifier, [iot_endpoint, args.endpoint])
                T.start()
            if args.use_custom_domain == True and not T.is_alive():
                logger.warning('dr_custom_endpoint_verifier thread not alive, restarting')
                iot_endpoint = resolve_cname(args.endpoint)
                T = threading.Timer(0, dr_custom_endpoint_verifier, [iot_endpoint, args.endpoint])
                T.start()

    # Wait for all messages to be received.
    # This waits forever if count was set to 0.
    if args.count != 0 and not received_all_event.is_set():
        logger.info("Waiting for all messages to be received...")

    received_all_event.wait()
    logger.info("%s message(s) received.", received_count)

    # Disconnect
    logger.info("Disconnecting... %s", MQTT_CONNECTION)
    disconnect_future = MQTT_CONNECTION.disconnect()
    disconnect_future.result()
    logger.info("Disconnected!")
    if T:
        logger.info('terminating T: {}'.format(T))
        T.cancel()
