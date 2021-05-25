#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.

# use `test-dr-deployment.py` as an automated end-to-end test to show the working
# capabilities of the IoT DR Solution.
# `Note` that you should execute the test program
# only after a successful deployment of the IoT DR Solution.

### covered test cases
# * `MATCH_CHECK` - create a device with cert/policy in the primary region.
# It should be replicated into the secondary region. The device name should be
# unique to avoid conflicts with existing devices. Compare if device is provisioned
# in the primary and secondary region. Device-name, attached policy-name and
# cert id should be the same in both regions.
# * `PUBSUB_CHECK` - test publish/subscribe in *both regions* with the device that
# was just created. A successful test should receive the number of messages that
# have been published.
# * `SHADOW_CHECK` - shadow test: Update the shadow for the device in the primary
# region. Verify that the shadow has been updated in the secondary region.
# * `DELETE_CHECK` - clean up: delete the device including cert/policy in the
# primary region. It should be deleted in the secondary region too.

import boto3
import logging
import json
import random
import sys
import time
import uuid
import argparse
import threading
import os
from awscrt import io, mqtt
from awsiot import mqtt_connection_builder
from datetime import datetime

logger = logging.getLogger()
for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
FORMAT = '%(asctime)s [%(levelname)s]: %(message)s'
h.setFormatter(logging.Formatter(FORMAT))
logger.addHandler(h)
logger.setLevel(logging.INFO)

parser = argparse.ArgumentParser(description="Test DR deployment end-to-end functionality")
parser.add_argument('--primary-region', required=True, help="Primary aws region.")
parser.add_argument('--secondary-region', required=True, help="Secondary aws region.")
args = parser.parse_args()

thingName = 'iot-dr-test-'+uuid.uuid4().hex
defaultPolicyName = 'test-dr-deployment-policy'
MQTT_CONNECTION = None
mqtt_client_id = "test-" + str(uuid.uuid4())
mqtt_client_id2 = "test-" + str(uuid.uuid4())

io.init_logging(getattr(io.LogLevel, io.LogLevel.NoLogs.name), 'stderr')

received_count = 0
num_msg = 5
received_all_event = threading.Event()

def createPolicy(client):
  try:
      client.create_policy(
        policyName=defaultPolicyName,
        policyDocument='{"Version": "2012-10-17","Statement": [{"Effect": "Allow","Action": "iot:*","Resource": "*"}]}',
        tags=[
            {
                'Key': 'string',
                'Value': 'string'
            },
        ]
      )
      logger.info('policy created with name: %s', defaultPolicyName)
  except client.exceptions.ResourceAlreadyExistsException:
      logger.info('policy exists with name: %s',defaultPolicyName)
      return {}

def createThing(client):
  client.create_thing(
      thingName = thingName
  )
  createCertificate(client)

def createCertificate(client):

    certResponse = client.create_keys_and_certificate(
    		setAsActive = True
    )
    data = json.loads(json.dumps(certResponse, sort_keys=False, indent=4))
    for element in data:
    		if element == 'certificateArn':
    				certificateArn = data['certificateArn']
    		elif element == 'keyPair':
    				PublicKey = data['keyPair']['PublicKey']
    				PrivateKey = data['keyPair']['PrivateKey']
    		elif element == 'certificatePem':
    				certificatePem = data['certificatePem']

    with open('public.key', 'w') as outfile:
    		outfile.write(PublicKey)
    with open('private.key', 'w') as outfile:
    		outfile.write(PrivateKey)
    with open('cert.pem', 'w') as outfile:
    		outfile.write(certificatePem)

    client.attach_policy(
    		policyName = defaultPolicyName,
    		target = certificateArn
    )
    client.attach_thing_principal(
    		thingName = thingName,
    		principal = certificateArn
    )

def cleanup(client, thing_name):
    policy_names = {}
    try:
        r_principals = client.list_thing_principals(thingName=thing_name)
    except Exception:
        r_principals = {'principals': []}

    for arn in r_principals['principals']:
        cert_id = arn.split('/')[1]

        client.detach_thing_principal(thingName=thing_name,principal=arn)
        client.update_certificate(certificateId=cert_id,newStatus='INACTIVE')
        r_policies = client.list_principal_policies(principal=arn)

        for pol in r_policies['policies']:
            pol_name = pol['policyName']
            policy_names[pol_name] = 1
            client.detach_policy(policyName=pol_name,target=arn)

        client.delete_certificate(certificateId=cert_id,forceDelete=True)

    client.delete_thing(thingName=thing_name)
    r_targets_pol = client.list_targets_for_policy(policyName=defaultPolicyName,pageSize=250)

    for arn in r_targets_pol['targets']:
        client.detach_policy(policyName=defaultPolicyName,target=arn)

    client.delete_policy(policyName=defaultPolicyName)

def checkThingCertPolicySync(client, thingName):
    try:
        returnCheck=[]
        response = client.describe_thing(thingName=thingName)
        if response:
            returnCheck.append(response['thingName'])
            response = client.list_thing_principals(thingName=thingName)
            for principal in response['principals']:
                response = client.describe_certificate(certificateId=principal.split('/')[-1])
                returnCheck.append(response['certificateDescription']['certificateId'])

                response = client.list_principal_policies(principal=principal)

                for policy in response['policies']:
                    response = client.get_policy(policyName=policy['policyName'])
                    returnCheck.append(response['policyDocument'])
            logger.info(returnCheck)
            return returnCheck
        else:
            return returnCheck
    except client.exceptions.ResourceNotFoundException as e:
        logger.info('thing: {} not found'.format(thingName))
        return returnCheck
    except Exception as e:
        logger.error('ERROR: %s',e)

def on_resubscribe_complete(resubscribe_future):
        resubscribe_results = resubscribe_future.result()
        logger.info("Resubscribe results: %s",resubscribe_results)

        for qos in resubscribe_results['topics']:
            if qos is None:
                os._exit(1)

# Callback when connection is accidentally lost.
def on_connection_interrupted(connection, error, **kwargs):
    logger.info("Connection interrupted. error: %s",error)


# Callback when an interrupted connection is re-established.
def on_connection_resumed(connection, return_code, session_present, **kwargs):
    logger.info("Connection resumed. return_code: %s session_present: %s",return_code, session_present)

    if return_code == mqtt.ConnectReturnCode.ACCEPTED and not session_present:
        logger.info("Session did not persist. Resubscribing to existing topics...")
        resubscribe_future, _ = connection.resubscribe_existing_topics()

        # Cannot synchronously wait for resubscribe result because we're on the connection's event-loop thread,
        # evaluate result with a callback instead.
        resubscribe_future.add_done_callback(on_resubscribe_complete)

# Callback when the subscribed topic receives a message
def on_message_received(topic, payload, **kwargs):
    logger.info("Received message from topic '%s': %s",topic, payload)
    global received_count
    received_count += 1
    if received_count == 5:
        received_all_event.set()

def mqtt_connection_start(client, mqttClientId, topic):
    global MQTT_CONNECTION

    endpoint = client.describe_endpoint(endpointType='iot:Data-ATS')['endpointAddress']
    # Spin up resources
    event_loop_group = io.EventLoopGroup(1)
    host_resolver = io.DefaultHostResolver(event_loop_group)
    client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)
    MQTT_CONNECTION = mqtt_connection_builder.mtls_from_path(
            endpoint=endpoint,
            cert_filepath='cert.pem',
            pri_key_filepath='private.key',
            client_bootstrap=client_bootstrap,
            ca_filepath='',
            on_connection_interrupted=on_connection_interrupted,
            on_connection_resumed=on_connection_resumed,
            client_id=mqttClientId,
            clean_session=True,
            keep_alive_secs=6)

    logger.info("Connecting to %s with client ID '%s'...", endpoint, mqttClientId)

    connect_future = MQTT_CONNECTION.connect()

    # Future.result() waits until a result is available
    connect_future.result()
    logger.info("Connected!")

    # Subscribe
    logger.info("Subscribing to topic '%s'...",topic)
    subscribe_future, packet_id = MQTT_CONNECTION.subscribe(
        topic=topic,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=on_message_received)

    subscribe_result = subscribe_future.result()
    logger.info("Subscribed with %s",str(subscribe_result['qos']))

def pubSubTests(client,thingName,clientId,topic,region):
    publish_count = 1
    while (publish_count <= num_msg):
        if not MQTT_CONNECTION:
            logger.warning('no active MQTT_CONNECTION will skip this publish cycle')
            continue

        message = {
            "message": "IoT DR test",
            "client_id": clientId,
            "count": "{}".format(publish_count),
            "datetime": "{}".format(datetime.now().isoformat())
        }
        logger.info('publish: topic: {} message: {}'.format(topic, message))
        MQTT_CONNECTION.publish(
            topic=topic,
            payload=json.dumps(message),
            qos=mqtt.QoS.AT_LEAST_ONCE)
        time.sleep(1)
        publish_count += 1
    if not received_all_event.is_set():
        logger.info("Waiting for all messages to be received...")

    received_all_event.wait()
    logger.info("%s message(s) received.",received_count)

    # Disconnect
    logger.info("Disconnecting... %s",MQTT_CONNECTION)
    disconnect_future = MQTT_CONNECTION.disconnect()
    disconnect_future.result()
    logger.info("Disconnected!")

def updateShadow(client, thingName):
    try:
        thing_name = thingName
        shadow_payload = {'state':{'reported':{'pressure': '{}'.format(random.randrange(20, 40))}}}
        logger.info(shadow_payload)

        client.update_thing_shadow(
            thingName=thing_name,
            payload=json.dumps(shadow_payload)
        )
        return shadow_payload
    except Exception as e:
        logger.error('%s',e)

def getShadow(client, thing_name):
    try:
        response = client.get_thing_shadow(
            thingName=thing_name
        )
        #logger.debug('response: {}'.format(response))
        payload = json.loads(response['payload'].read())
        logger.info(payload)
        return payload

    except client.exceptions.ResourceNotFoundException:
        logger.warning('thing_name: %s: shadow does not exist',thing_name)
        return {}
    except Exception as e:
        logger.error('replication: %s',e)

#MAIN
try:
    #TEST CASES OBJECT
    Tests = {
    "MATCH_CHECK": "FAILED",
    "PUBSUB_CHECK": {args.primary_region:"FAILED",args.secondary_region:"FAILED"},
    "SHADOW_CHECK": "FAILED",
    "DELETE_CHECK": "FAILED"
    }

    #REGIONS OBJECT
    regs = {"primaryRegion":args.primary_region, "secondaryRegion":args.secondary_region}

    #GET SUPPORTED REGIONS
    s = boto3.Session()
    iot_regions = s.get_available_regions('iot')

    #CHECK IF REGION ARGS ARE VALID
    if args.primary_region not in iot_regions or args.secondary_region not in iot_regions:
        logger.error("one of your chosen regions is not valid: "+json.dumps(regs, indent=4))
        logger.error("supported regions are:%s",json.dumps(iot_regions, indent=4))
        os._exit(1)

    #CREATE REGION-SESSIONS
    session_p = boto3.Session(region_name=args.primary_region)
    session_s = boto3.Session(region_name=args.secondary_region)

    #CREATE IOT-CLIENTS
    c_iot_p = session_p.client('iot')
    c_iot_s = session_s.client('iot')

    # IOT ENDPOINTS
    endpoint_p = c_iot_p.describe_endpoint(endpointType='iot:Data-ATS')['endpointAddress']
    endpoint_s = c_iot_s.describe_endpoint(endpointType='iot:Data-ATS')['endpointAddress']

    #CREATE IOT-DATA CLIENTS (USED FOR SHADOWS)
    c_iot_p_data = session_p.client('iot-data', endpoint_url='https://{}'.format(endpoint_p))
    c_iot_s_data = session_s.client('iot-data', endpoint_url='https://{}'.format(endpoint_s))

    #CREATE THING WITH NEW POLICY & CERT
    createPolicy(c_iot_p)
    createThing(c_iot_p)
    logger.info('CHECK THING SYNC | CERT | POLICY MATCHES')

    #CHECK THING REGION SYNC
    logger.info('get thing infos from primary region')
    hash_primary=''.join(checkThingCertPolicySync(c_iot_p, thingName))
    logger.info("Wait for region syncer to create new thing in: %s ...",args.secondary_region.upper())
    time.sleep(15)
    logger.info('get thing infos from secondary region')
    hash_secondary=''.join(checkThingCertPolicySync(c_iot_s, thingName))

    if hash_primary == hash_secondary:
       logger.info("MATCH")
       Tests['MATCH_CHECK'] = "PASSED"
    else:
       logger.info("NO MATCH")

    #CHECK PUBSUB - PRIMARY
    logger.info('CHECK PUBSUB in: %s',args.primary_region.upper())
    mqtt_connection_start(c_iot_p, mqtt_client_id, "test/topic")
    pubSubTests(c_iot_p, thingName, mqtt_client_id, "test/topic",args.primary_region.upper())
    if received_count == num_msg:
        Tests['PUBSUB_CHECK'][args.primary_region] = "PASSED"
    #CHECK PUBSUB - SECONDARY
    logger.info('CHECK PUBSUB in: %s',args.secondary_region.upper())
    mqtt_connection_start(c_iot_s, mqtt_client_id2, "test/topic")
    pubSubTests(c_iot_s, thingName, mqtt_client_id2, "test/topic",args.secondary_region.upper())
    if received_count == num_msg*2:
        Tests['PUBSUB_CHECK'][args.secondary_region] = "PASSED"

    #CHECK SHADOW UPDATE
    logger.info('UPDATING SHADOW of thing: %s in: %s',thingName, args.primary_region.upper())
    sourceShadow = updateShadow(c_iot_p_data, thingName)
    logger.info("Waiting for region syncer to update shadow in: %s ...",args.secondary_region.upper())
    time.sleep(15)
    logger.info('GETTING  SHADOW of thing: %s in: %s',thingName, args.secondary_region.upper())
    targetShadow = getShadow(c_iot_s_data, thingName)

    if sourceShadow['state'] == targetShadow['state']:
        Tests['SHADOW_CHECK'] = "PASSED"

    #CHECK DELETE IN BOTH REGIONS
    logger.info('DELETING THING: %s in: %s',thingName, args.primary_region.upper())
    cleanup(c_iot_p, thingName)
    deleteCheck1=checkThingCertPolicySync(c_iot_p, thingName)
    logger.info("Waiting for region syncer to delete thing in: %s ...",args.secondary_region.upper())
    time.sleep(15)
    deleteCheck2=checkThingCertPolicySync(c_iot_s, thingName)
    if deleteCheck1 == [] and deleteCheck2 == []:
       Tests['DELETE_CHECK'] = "PASSED"

    #TESTREPORT
    logger.info('"TESTS" : '+json.dumps(Tests, indent=4))

except Exception as e:
    logger.error('ERROR: %s',e)
    logger.error('"TESTS" : '+json.dumps(Tests, indent=4))
    cleanup(c_iot_p, thingName)
    os._exit(1)