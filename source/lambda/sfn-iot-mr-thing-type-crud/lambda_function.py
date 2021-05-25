#
# thing type crud
#
"""IoT DR: Lambda function to handle
thing type CreateUpdateDelete"""

import logging
import sys

import boto3

logger = logging.getLogger()
for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
FORMAT = '%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)s - %(funcName)s - %(message)s'
h.setFormatter(logging.Formatter(FORMAT))
logger.addHandler(h)
logger.setLevel(logging.INFO)


class ThingTypeCrudException(Exception): pass


def deprecate_type(c_iot, thing_type_name, bool):
    logger.info('thing_type_name: {} undo deprecate bool: {}'.format(thing_type_name, bool))
    try:
        response = c_iot.deprecate_thing_type(thingTypeName=thing_type_name, undoDeprecate=bool)
        logger.info('response: {}'.format(response))
    except c_iot.exceptions.ResourceNotFoundException:
        logger.info('thing_type_name {} does not exist'.format(thing_type_name))
        return False

    except Exception as e:
        logger.error('{}'.format(e))
        raise(e)


def thing_type_exists(c_iot, thing_type_name):
    logger.info("thing type exists: thing_type_name: {}".format(thing_type_name))
    try:
        response = c_iot.describe_thing_type(thingTypeName=thing_type_name)
        logger.info('response: {}'.format(response))
        return True

    except c_iot.exceptions.ResourceNotFoundException:
        logger.info('thing_type_name {} does not exist'.format(thing_type_name))
        return False

    except Exception as e:
        logger.error('{}'.format(e))
        raise(e)


def delete_type(c_iot, thing_type_name):
    logger.info('thing_type_name: {}'.format(thing_type_name))
    try:
        response = c_iot.delete_thing_type(thingTypeName=thing_type_name)
        logger.info('response: {}'.format(response))
    except c_iot.exceptions.ResourceNotFoundException:
        logger.info('thing_type_name {} does not exist'.format(thing_type_name))
        return False

    except Exception as e:
        logger.error('{}'.format(e))
        raise(e)


def update_thing_type(c_iot, thing_name, thing_type_name):
    try:
        if thing_type_name == None:
            response = c_iot.update_thing(
                thingName=thing_name,
                removeThingType=True
            )
        else:
            response = c_iot.update_thing(
                thingName=thing_name,
                thingTypeName=thing_type_name,
                removeThingType=False
            )
        logger.info("update thing type: {}".format(response))
    except Exception as e:
        logger.error("update_thing_type: {}".format(e))
        raise(e)


def create_thing_type(c_iot, thing_type_name):
    logger.info("create thing type: thing_type_name: {}".format(thing_type_name))
    try:
        if not thing_type_exists(c_iot, thing_type_name):
            response = c_iot.create_thing_type(thingTypeName=thing_type_name)
            logger.info("create_thing_type: response: {}".format(response))
        else:
            logger.info("thing type exists already: {}".format(thing_type_name))
    except c_iot.exceptions.ResourceAlreadyExistsException:
        logger.info('exists already thing_type_name: {}'.format(thing_type_name))
    except Exception as e:
        logger.error("create_thing_type: {}".format(e))
        raise(e)


def lambda_handler(event, context):
    logger.info('event: {}'.format(event))
    try:
        c_iot = boto3.client('iot')

        if event['NewImage']['eventType']['S'] == 'THING_TYPE_EVENT':
            if event['NewImage']['operation']['S'] == 'CREATED':
                thing_type_name = event['NewImage']['thingTypeName']['S']
                logger.info("thing_type_name: {}".format(thing_type_name))
                create_thing_type(c_iot, thing_type_name)

            elif event['NewImage']['operation']['S'] == 'UPDATED':
                if 'isDeprecated' in event['NewImage'] and event['NewImage']['isDeprecated']['BOOL'] is True:
                    thing_type_name = event['NewImage']['thingTypeName']['S']
                    deprecate_type(c_iot, thing_type_name, False)

                elif 'isDeprecated' in event['NewImage'] and event['NewImage']['isDeprecated']['BOOL'] is False:
                    thing_type_name = event['NewImage']['thingTypeName']['S']
                    deprecate_type(c_iot, thing_type_name, True)

            elif event['NewImage']['operation']['S'] == 'DELETED':
                thing_type_name = event['NewImage']['thingTypeName']['S']
                logger.info("thing_type_name: {}".format(thing_type_name))
                delete_type(c_iot, thing_type_name)

        elif event['NewImage']['eventType']['S'] == 'THING_TYPE_ASSOCIATION_EVENT':
            if event['NewImage']['operation']['S'] == 'ADDED':
                thing_name = event['NewImage']['thingName']['S']
                thing_type_name = event['NewImage']['thingTypeName']['S']
                logger.info("ADDED: thing_name: {} thing_type_name: {}".format(thing_name, thing_type_name))
                update_thing_type(c_iot, thing_name, thing_type_name)

            elif event['NewImage']['operation']['S'] == 'REMOVED':
                thing_name = event['NewImage']['thingName']['S']
                thing_type_name = event['NewImage']['thingTypeName']['S']
                logger.info("REMOVED: thing_name: {} thing_type_name: {}".format(thing_name, thing_type_name))
                update_thing_type(c_iot, thing_name, None)

    except Exception as e:
        logger.error(e)
        raise ThingTypeCrudException('{}'.format(e))

    return {"message": "success"}
