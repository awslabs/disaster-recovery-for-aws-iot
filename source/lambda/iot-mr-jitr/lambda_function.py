#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#required libraries
import boto3
import json
import logging
import os
import sys

from OpenSSL import crypto

# configure logging
logger = logging.getLogger()
for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
FORMAT = '%(asctime)s [%(levelname)s]: %(threadName)s-%(filename)s:%(lineno)s-%(funcName)s: %(message)s'
h.setFormatter(logging.Formatter(FORMAT))
logger.addHandler(h)
logger.setLevel(logging.INFO)

IOT_POLICY_NAME = os.environ.get('IOT_POLICY_NAME', 'IoTDR-JITR_Policy')

ERRORS = []


def get_thing_name(c_iot, certificate_id, response):
    try:
        cert_pem = response['certificateDescription']['certificatePem']
        logger.info('cert_pem: {}'.format(cert_pem))

        cert = crypto.load_certificate(crypto.FILETYPE_PEM, cert_pem)

        subject = cert.get_subject()
        cn = subject.CN
        logger.info('subject: {} cn: {}'.format(subject, cn))
        return cn
    except Exception as e:
        logger.warn('unable to get CN from certificate_id: {}: {}, using certificate_id as thing name'.format(certificate_id, e))
        return certificate_id


def thing_exists(c_iot, thing_name):
    try:
        logger.info('thing_name: {}'.format(thing_name))
        response = c_iot.describe_thing(thingName=thing_name)
        print('response: {}'.format(response))
        return True

    except c_iot.exceptions.ResourceNotFoundException:
        logger.info('thing_name "{}" does not exist'.format(thing_name))
        return False

    except Exception as e:
        logger.error('{}'.format(e))
        raise Exception(e)


def create_thing(c_iot, thing_name):
    global ERRORS
    try:
        logger.info('thing_name: {}'.format(thing_name))
        if not thing_exists(c_iot, thing_name):
            response = c_iot.create_thing(thingName=thing_name)
            logger.info("create_thing: response: {}".format(response))
        else:
            logger.info("thing exists already: {}".format(thing_name))
    except Exception as e:
        logger.error("create_thing: {}".format(e))
        ERRORS.append("create_thing: {}".format(e))


def policy_exists(c_iot, policy_name):
    try:
        logger.info('policy_name: {}'.format(policy_name))
        response = c_iot.get_policy(policyName=policy_name)
        print('response: {}'.format(response))
        return True

    except c_iot.exceptions.ResourceNotFoundException:
        logger.info('policy_name: {}: does not exist'.format(policy_name))
        return False

    except Exception as e:
        logger.error('{}'.format(e))
        raise Exception(e)


def create_iot_policy(c_iot, policy_name):
    global ERRORS
    policy_document = {
        "Version":"2012-10-17",
        "Statement":[
            {
                "Effect": "Allow",
                "Action": [
                  "iot:Connect"
                ],
                "Resource": [
                  "arn:aws:iot:*:*:client/${iot:Connection.Thing.ThingName}"
                ]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "iot:Publish",
                    "iot:Receive"
                ],
                "Resource": [
                    "arn:aws:iot:*:*:topic/dt/${iot:Connection.Thing.ThingName}/*",
                    "arn:aws:iot:*:*:topic/cmd/${iot:Connection.Thing.ThingName}/*",
                    "arn:aws:iot:*:*:topic/$aws/things/${iot:Connection.Thing.ThingName}/shadow/*"
                ]
            },
            {
                "Effect": "Allow",
                "Action": [
                    "iot:Subscribe"
                ],
                "Resource": [
                    "arn:aws:iot:*:*:topicfilter/dt/${iot:Connection.Thing.ThingName}/*",
                    "arn:aws:iot:*:*:topicfilter/cmd/${iot:Connection.Thing.ThingName}/*",
                    "arn:aws:iot:*:*:topicfilter/$aws/things/${iot:Connection.Thing.ThingName}/shadow/*"
                ]
            }
        ]
    }

    try:
        logger.info('policy_name: {}'.format(policy_name))
        if not policy_exists(c_iot, policy_name):
            response = c_iot.create_policy(
                policyName=policy_name,
                policyDocument=json.dumps(policy_document)
            )
            logger.info("create_iot_policy: response: {}".format(response))
        else:
            logger.info("policy exists already: {}".format(policy_name))
    except c_iot.exceptions.ResourceAlreadyExistsException:
        logger.warn('policy_name {}: exists already - might have been created in a parallel thread'.format(policy_name))
    except Exception as e:
        logger.error("create_iot_policy: {}".format(e))
        ERRORS.append("create_iot_policy: {}".format(e))


def activate_certificate(c_iot, certificate_id):
    global ERRORS
    try:
        logger.info('certificate_id: {}'.format(certificate_id))
        response = c_iot.update_certificate(certificateId=certificate_id, newStatus='ACTIVE')
        logger.info("activate_cert: response: {}".format(response))
    except Exception as e:
        logger.error("activate_certificate: {}".format(e))
        ERRORS.append("activate_certificate: {}".format(e))


def attach_policy(c_iot, thing_name, policy_name, response):
    global ERRORS
    try:
        logger.info('thing_name: {} policy_name: {}'.format(thing_name, policy_name))
        certificate_arn = response['certificateDescription']['certificateArn']
        logger.info("certificate_arn: {}".format(certificate_arn))

        response = c_iot.attach_thing_principal(thingName=thing_name, principal=certificate_arn)
        logger.info("attach_thing_principal: response: {}".format(response))

        response = c_iot.attach_policy(policyName=policy_name, target=certificate_arn)
        logger.info("attach_policy: response: {}".format(response))
    except Exception as e:
        logger.error("attach_policy: {}".format(e))
        ERRORS.append("attach_policy: {}".format(e))


def lambda_handler(event, context):
    logger.info("event: {}".format(event))
    logger.info(json.dumps(event, indent=4))

    region = os.environ["AWS_REGION"]
    logger.info("region: {}".format(region))

    try:
        ca_certificate_id = event['caCertificateId']
        certificate_id = event['certificateId']
        certificate_status = event['certificateStatus']

        logger.info("ca_certificate_id: " + ca_certificate_id)
        logger.info("certificate_id: " + certificate_id)
        logger.info("certificate_status: " + certificate_status)

        c_iot = boto3.client('iot')

        res_desc_cert = c_iot.describe_certificate(certificateId=certificate_id)
        logger.info('res_desc_cert: {}'.format(res_desc_cert))

        thing_name = get_thing_name(c_iot, certificate_id, res_desc_cert)
        create_thing(c_iot, thing_name)
        create_iot_policy(c_iot, IOT_POLICY_NAME)
        activate_certificate(c_iot, certificate_id)
        attach_policy(c_iot, thing_name, IOT_POLICY_NAME, res_desc_cert)
    except Exception as e:
        logger.error('describe_certificate: {}'.format(e))
        return {"status": "error", "message": '{}'.format(e)}

    if ERRORS:
        return {"status": "error", "message": '{}'.format(ERRORS)}

    return {"status": "success"}
