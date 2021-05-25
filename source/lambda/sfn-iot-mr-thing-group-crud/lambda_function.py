#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#
# thing group crud
#

import logging

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


ERRORS = []

class ThingGroupCrudException(Exception): pass


def thing_group_exists(c_iot, thing_group_name):
    logger.info("thing group exists: thing_group_name: {}".format(thing_group_name))
    try:
        response = c_iot.describe_thing_group(thingGroupName=thing_group_name)
        logger.info('response: {}'.format(response))
        return True

    except c_iot.exceptions.ResourceNotFoundException:
        logger.info('thing_group_name {} does not exist'.format(thing_group_name))
        return False

    except Exception as e:
        logger.error('{}'.format(e))
        raise Exception(e)


def create_thing_group(c_iot, thing_group_name, description, attrs, merge):
    logger.info("create thing group: thing_group_name: {}".format(thing_group_name))
    global ERRORS
    try:
        if not thing_group_exists(c_iot, thing_group_name):
            response = c_iot.create_thing_group(
                thingGroupName=thing_group_name,
                thingGroupProperties={
                    'thingGroupDescription': description,
                    'attributePayload': {
                        'attributes': attrs,
                        'merge': merge
                    }
                }
            )
            logger.info("create_thing_group: response: {}".format(response))
        else:
            logger.info("thing group exists already: {}".format(thing_group_name))
    except Exception as e:
        logger.error("create_thing_group: {}".format(e))
        ERRORS.append("create_thing_group: {}".format(e))


def delete_thing_group(c_iot, thing_group_name):
    logger.info("delete thing group: thing_group_name: {}".format(thing_group_name))
    global ERRORS
    try:
        response = c_iot.delete_thing_group(thingGroupName=thing_group_name)
        logger.info('delete_thing_group: {}'.format(response))
    except Exception as e:
        logger.error("create_thing_group: {}".format(e))
        ERRORS.append("create_thing_group: {}".format(e))


def update_thing_group(c_iot, thing_group_name, description, attrs, merge):
    logger.info("update thing group: thing_group_name: {}".format(thing_group_name))
    global ERRORS
    try:
        create_thing_group(c_iot, thing_group_name, "", {}, True)
        response = c_iot.update_thing_group(
            thingGroupName=thing_group_name,
            thingGroupProperties={
                'thingGroupDescription': description,
                'attributePayload': {
                    'attributes': attrs,
                    'merge': merge
                }
            }
        )
        logger.info('update_thing_group: {}'.format(response))
    except Exception as e:
        logger.error("create_thing_group: {}".format(e))
        ERRORS.append("create_thing_group: {}".format(e))



def add_thing_to_group(c_iot, thing_group_name, thing_name):
    logger.info("add thing to group: thing_group_name: {} thing_name: {}".format(thing_group_name, thing_name))
    global ERRORS
    try:
        create_thing_group(c_iot, thing_group_name, "", {}, True)
        response = c_iot.add_thing_to_thing_group(
            thingGroupName=thing_group_name,
            thingName=thing_name,
            overrideDynamicGroups=False)
        logger.info("add_thing_to_group: {}".format(response))
    except Exception as e:
        logger.error("add_thing_to_group: {}".format(e))
        ERRORS.append("add_thing_to_group: {}".format(e))


def remove_thing_from_group(c_iot, thing_group_name, thing_name):
    logger.info("remove thing from group: thing_group_name: {} thing_name: {}".format(thing_group_name, thing_name))
    global ERRORS
    try:
        response = c_iot.remove_thing_from_thing_group(
            thingGroupName=thing_group_name,
            thingName=thing_name)
        logger.info("remove_thing_from_group: {}".format(response))
    except Exception as e:
        logger.error("add_thing_to_group: {}".format(e))
        ERRORS.append("add_thing_to_group: {}".format(e))


def lambda_handler(event, context):
    global ERRORS
    ERRORS = []

    logger.info('event: {}'.format(event))

    try:
        c_iot = boto3.client('iot')

        if event['NewImage']['eventType']['S'] == 'THING_GROUP_EVENT':
            thing_group_name = event['NewImage']['thingGroupName']['S']
            logger.info("operation: {} thing_group_name: {}".
                format(event['NewImage']['operation']['S'], thing_group_name))
            if event['NewImage']['operation']['S'] == 'CREATED':
                description = ""
                if 'S' in event['NewImage']['description']:
                    description = event['NewImage']['description']['S']

                attrs = {}
                if 'M' in event['NewImage']['attributes']:
                    for key in event['NewImage']['attributes']['M']:
                        attrs[key] = event['NewImage']['attributes']['M'][key]['S']

                merge = True
                if attrs:
                    merge = False
                logger.info('description: {} attrs: {}'.format(description, attrs))
                create_thing_group(c_iot, thing_group_name, description, attrs, merge)
            elif event['NewImage']['operation']['S'] == 'DELETED':
                delete_thing_group(c_iot, thing_group_name)
            elif event['NewImage']['operation']['S'] == 'UPDATED':
                description = ""
                if 'S' in event['NewImage']['description']:
                    description = event['NewImage']['description']['S']

                attrs = {}
                if 'M' in event['NewImage']['attributes']:
                    for key in event['NewImage']['attributes']['M']:
                        attrs[key] = event['NewImage']['attributes']['M'][key]['S']

                merge = True
                if attrs:
                    merge = False
                logger.info('description: {} attrs: {}'.format(description, attrs))
                update_thing_group(c_iot, thing_group_name, description, attrs, merge)
        elif event['NewImage']['eventType']['S'] == 'THING_GROUP_MEMBERSHIP_EVENT':
            group_arn = event['NewImage']['groupArn']['S']
            thing_arn = event['NewImage']['thingArn']['S']
            thing_group_name = group_arn.split('/')[-1]
            thing_name = thing_arn.split('/')[-1]
            logger.info("operation: {} group_arn: {} thing_arn: {} thing_group_name: {} thing_name: {}".
                format(event['NewImage']['operation']['S'], group_arn, thing_arn, thing_group_name, thing_name))
            if event['NewImage']['operation']['S'] == 'ADDED':
                add_thing_to_group(c_iot, thing_group_name, thing_name)
            elif event['NewImage']['operation']['S'] == 'REMOVED':
                remove_thing_from_group(c_iot, thing_group_name, thing_name)

    except Exception as e:
        logger.error(e)
        ERRORS.append("lambda_handler: {}".format(e))

    if ERRORS:
        error_message = ', '.join(ERRORS)
        logger.error('{}'.format(error_message))
        raise ThingGroupCrudException('{}'.format(error_message))

    return {"message": "success"}
