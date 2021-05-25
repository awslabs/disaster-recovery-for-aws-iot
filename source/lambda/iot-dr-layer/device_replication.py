#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#
# device registry - layer for common used functions
#
"""IoT DR: device registry functions.
Will be deployed as Lambda layer."""

import logging
import sys
import time

import boto3

logger = logging.getLogger()
for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
FORMAT = '%(asctime)s [%(levelname)s] - %(filename)s:%(lineno)s - %(funcName)s - %(message)s'
h.setFormatter(logging.Formatter(FORMAT))
logger.addHandler(h)
logger.setLevel(logging.INFO)


class DeviceReplicationCreateThingException(Exception): pass

class DeviceReplicationDeleteThingException(Exception): pass

class DeviceReplicationUpdateThingException(Exception): pass

class DeviceReplicationGeneralException(Exception): pass


def get_iot_data_endpoint(region, iot_endpoints):
    try:
        logger.info('region: {} iot_endpoints: {}'.format(region, iot_endpoints))
        iot_data_endpoint = None
        for endpoint in iot_endpoints:
            if region in endpoint:
                logger.info('region: {} in endpoint: {}'.format(region, endpoint))
                iot_data_endpoint = endpoint
                break

        if iot_data_endpoint is None:
            logger.info('iot_data_endpoint not found calling describe_endpoint')
            iot_data_endpoint = (
                boto3.client('iot').
                describe_endpoint(endpointType='iot:Data-ATS')['endpointAddress']
            )
            logger.info('iot_data_endpoint from describe_endpoint: {}'.format(iot_data_endpoint))
        else:
            logger.info('iot_data_endpoint from iot_endpoints: {}'.format(iot_data_endpoint))

        return iot_data_endpoint
    except Exception as e:
        logger.error('{}'.format(e))
        raise DeviceReplicationGeneralException(e)


def thing_exists(c_iot, thing_name):
    logger.debug("entering thing_exists: thing_name: {}".format(thing_name))
    try:
        response = c_iot.describe_thing(thingName=thing_name)
        logger.debug('response: {}'.format(response))
        logger.info('thing_name "{}" exists'.format(thing_name))
        return True

    except c_iot.exceptions.ResourceNotFoundException:
        logger.info('thing_name "{}" does not exist'.format(thing_name))
        return False

    except Exception as e:
        logger.error('{}'.format(e))
        raise DeviceReplicationGeneralException(e)


def policy_exists(c_iot, policy_name):
    logger.info("policy_exists: policy_name: {}".format(policy_name))
    try:
        response = c_iot.get_policy(policyName=policy_name)
        logger.debug('response: {}'.format(response))
        logger.info('policy_name: {}: exists'.format(policy_name))
        return True

    except c_iot.exceptions.ResourceNotFoundException:
        logger.info('policy_name: {}: does not exist'.format(policy_name))
        return False

    except Exception as e:
        logger.error('{}'.format(e))
        raise DeviceReplicationGeneralException(e)


def certificate_exists(c_iot, cert_id):
    logger.info("certificate_exists: cert_id: {}".format(cert_id))
    try:
        response = c_iot.describe_certificate(certificateId=cert_id)
        logger.debug('response: {}'.format(response))
        logger.info('cert id "{}" exists'.format(cert_id))
        return True

    except c_iot.exceptions.ResourceNotFoundException:
        logger.info('cert_id "{}" does not exist'.format(cert_id))
        return False

    except Exception as e:
        logger.error('{}'.format(e))
        raise DeviceReplicationGeneralException(e)


def thing_type_exists(c_iot, thing_type_name):
    logger.info("thing_type_exists: thing_type_name: {}".format(thing_type_name))
    try:
        response = c_iot.describe_thing_type(thingTypeName=thing_type_name)
        logger.debug('response: {}'.format(response))
        logger.info('thing_type_name "{}" exists'.format(thing_type_name))
        return True

    except c_iot.exceptions.ResourceNotFoundException:
        logger.info('thing_type_name "{}" does not exist'.format(thing_type_name))
        return False

    except Exception as e:
        logger.error('{}'.format(e))
        raise DeviceReplicationGeneralException(e)


def create_thing_type(c_iot, thing_type_name):
    logger.info('create_thing_type: thing_type_name: {}'.format(thing_type_name))
    try:
        if not thing_type_exists(c_iot, thing_type_name):
            response = c_iot.create_thing_type(thingTypeName=thing_type_name)
            logger.info('create_thing_type: response: {}'.format(response))
    except Exception as e:
        logger.error('create_thing_type: {}'.format(e))
        raise DeviceReplicationCreateThingException(e)


def create_thing(c_iot, c_iot_primary, thing_name, thing_type_name, attrs):
    logger.info('create_thing: thing_name: {} thing_type_name: {} attrs: {}'.
        format(thing_name, thing_type_name, attrs))
    try:
        if not thing_exists(c_iot_primary, thing_name):
            logger.warning(
                'thing_name "{}" does not exist in primary region "{}", will not being created'.
                format(thing_name, c_iot_primary.meta.region_name))
            return

        if not thing_exists(c_iot, thing_name):
            if thing_type_name and attrs:
                logger.info('thing_name: {}: thing_type_name and attrs'.format(thing_name))
                create_thing_type(c_iot, thing_type_name)
                response = c_iot.create_thing(
                    thingName=thing_name,
                    thingTypeName=thing_type_name,
                    attributePayload=attrs
                )
            elif not thing_type_name and attrs:
                logger.info('thing_name: {}: not thing_type_name and attrs'.format(thing_name))
                response = c_iot.create_thing(
                    thingName=thing_name,
                    attributePayload=attrs
                )
            elif thing_type_name and not attrs:
                logger.info('thing_name: {}: thing_type_name and not attrs'.format(thing_name))
                create_thing_type(c_iot, thing_type_name)
                response = c_iot.create_thing(
                    thingName=thing_name,
                    thingTypeName=thing_type_name
                )
            else:
                logger.info('not thing_type_name and not attrs')
                response = c_iot.create_thing(
                    thingName=thing_name
                )
            logger.info('thing_name: {}: create_thing: response: {}'.format(thing_name, response))
        else:
            logger.info('thing_name: {}: thing exists already'.format(thing_name))
    except Exception as e:
        logger.error('thing_name: {}: create_thing: {}'.format(thing_name, e))
        raise DeviceReplicationCreateThingException(e)


def get_thing_principals(c_iot_primary, thing_name):
    try:
        response = c_iot_primary.list_thing_principals(thingName=thing_name)
        logger.debug(response)
        logger.info('thing_name: {}: principals: {}'.format(thing_name, response['principals']))
        return response['principals']
    except Exception as e:
        logger.error('thing_name: {}: get_thing_principals: {}'.format(thing_name, e))
        raise DeviceReplicationGeneralException(e)


def get_principal_things(c_iot, principal):
    try:
        response = c_iot.list_principal_things(maxResults=10, principal=principal)
        logger.info('principal: {} things attached: {}'.format(principal, response['things']))
        return response['things']
    except Exception as e:
        logger.error('{}'.format(e))
        raise DeviceReplicationGeneralException(e)


def get_attached_policies(c_iot_primary, cert_arn):
    try:
        response = c_iot_primary.list_attached_policies(
            target=cert_arn, recursive=False, pageSize=10
        )
        logger.debug(response)
        logger.info('cert_arn: {}: policies: {}'.format(cert_arn, response['policies']))
        return response['policies']
    except Exception as e:
        logger.error('cert_arn: {}: get_attached_policies: {}'.format(cert_arn, e))
        raise DeviceReplicationGeneralException(e)


def get_and_create_policy(c_iot, c_iot_primary, policy_name):
    try:
        primary_region = c_iot_primary.meta.region_name
        secondary_region = c_iot.meta.region_name
        logger.info(
            'primary_region: {} secondary_region: {} policy_name: {}'.format(
                primary_region, secondary_region, policy_name
            )
        )

        response = c_iot_primary.get_policy(policyName=policy_name)
        logger.debug(response)
        logger.info('primary_region: {} policy_document: {}'.format(
            primary_region, response['policyDocument']))
        policy_document_this_region = response['policyDocument'].replace(
            primary_region, secondary_region
        )
        logger.info('secondary_region: {} policy_document: {}'.format(
            secondary_region, policy_document_this_region))
        response = c_iot.create_policy(
            policyName=policy_name,
            policyDocument=policy_document_this_region
        )
        logger.info('policy_name: {}: create_policy: response: {}'.format(policy_name, response))
    except c_iot.exceptions.ResourceAlreadyExistsException:
        logger.warning(
            'policy_name {}: exists already - might have been created in a parallel thread'.format(
                policy_name
            )
        )
    except Exception as e:
        logger.error('policy_name: {}: get_and_create_policy: {}'.format(policy_name, e))
        raise DeviceReplicationCreateThingException(e)


def register_cert(c_iot, cert_pem):
    try:
        response = c_iot.register_certificate_without_ca(certificatePem=cert_pem, status='ACTIVE')
        logger.info(response)
    except c_iot.exceptions.ResourceAlreadyExistsException:
        logger.warning(
            'certificate exists already - might be created in another thread'
        )
    except Exception as e:
        logger.error('register_cert: {}'.format(e))
        raise DeviceReplicationCreateThingException(e)


def create_thing_with_cert_and_policy(
    c_iot, c_iot_primary, thing_name, thing_type_name, attrs, retries, wait):
    primary_region = c_iot_primary.meta.region_name
    secondary_region = c_iot.meta.region_name
    logger.info(
        'thing_name: {} primary_region: {} secondary_region: {}'.format(
            thing_name, primary_region, secondary_region
        )
    )

    try:
        if not thing_exists(c_iot_primary, thing_name):
            logger.warning(
                'thing_name "{}" does not exist in primary region "{}", will not be created'.
                    format(thing_name, primary_region
                )
            )
            return

        logger.debug('calling create_thing: c_iot: {} c_iot_primary: {} \
        thing_name: {} thing_type_name: {} attrs: {}'.
            format(c_iot, c_iot_primary, thing_name, thing_type_name, attrs))
        create_thing(c_iot, c_iot_primary, thing_name, thing_type_name, attrs)

        principals = []
        retries = retries
        wait = wait
        i = 1
        while not principals and i <= retries:
            logger.info('{}: get_thing_principals for thing_name: {}'.format(i, thing_name))
            i += 1
            principals = get_thing_principals(c_iot_primary, thing_name)
            time.sleep(wait*i)

        if not principals:
            logger.error('thing_name: {}: no principals attached'.format(thing_name))
            raise DeviceReplicationCreateThingException(
                'no principals attached to thing_name: {}'.format(thing_name))

        for principal in principals:
            cert_id = principal.split('/')[-1]
            logger.info(
                'thing_name: {}: principal: {} cert_id: {}'.format(
                    thing_name, principal, cert_id
                )
            )

            response = c_iot_primary.describe_certificate(certificateId=cert_id)
            cert_arn = response['certificateDescription']['certificateArn']
            cert_pem = response['certificateDescription']['certificatePem']
            logger.info('thing_name: {}: cert_arn: {}'.format(thing_name, cert_arn))
            cert_arn_secondary_region = cert_arn.replace(primary_region, secondary_region)
            logger.info(
                'thing_name: {}: cert_arn_secondary_region: {}'.format(
                    thing_name, cert_arn_secondary_region
                )
            )

            if not certificate_exists(c_iot, cert_id):
                logger.info('thing_name: {}: register certificate without CA'.format(thing_name))
                register_cert(c_iot, cert_pem)

            policies = []
            retries = retries
            wait = wait
            i = 1
            while not policies and i <= retries:
                logger.info(
                    'thing_name: {}: {}: get_attached_policies for cert_arn: {}'.format(
                        thing_name, i, cert_arn
                    )
                )
                i += 1
                policies = get_attached_policies(c_iot_primary, cert_arn)
                time.sleep(wait*i)

            if not policies:
                logger.error(
                    'thing_name: {}: no policies attached to cert_arn: {}'.format(
                        thing_name, cert_arn
                    )
                )
                raise DeviceReplicationCreateThingException(
                    'no policies attached to cert_arn: {}'.format(cert_arn))

            for policy in policies:
                policy_name = policy['policyName']
                logger.info('thing_name: {}: policy_name: {}'.format(thing_name, policy_name))

                if not policy_exists(c_iot, policy_name):
                    logger.info('thing_name: {}: get_and_create_policy'.format(thing_name))
                    get_and_create_policy(c_iot, c_iot_primary, policy_name)

                response2 = c_iot.attach_policy(
                    policyName=policy_name,
                    target=cert_arn_secondary_region
                )
                logger.info(
                    'thing_name: {}: response attach_policy: {}'.format(
                        thing_name, response2
                    )
                )

            response3 = c_iot.attach_thing_principal(
                thingName=thing_name,
                principal=cert_arn_secondary_region
            )
            logger.info(
                'thing_name: {} response attach_thing_principal: {}'.format(
                    thing_name, response3
                )
            )

    except Exception as e:
        logger.error('thing_name: {}: create_thing_with_cert_and_policy: {}'.format(thing_name, e))
        raise DeviceReplicationCreateThingException(e)


def delete_shadow(thing_name, iot_data_endpoint):
    try:
        c_iot_data =  boto3.client('iot-data', endpoint_url='https://{}'.format(iot_data_endpoint))
        response = c_iot_data.delete_thing_shadow(thingName=thing_name)
        logger.info(
            'thing_name: {}: delete_thing_shadow: response: {}'.format(
                thing_name, response
            )
        )
    except c_iot_data.exceptions.ResourceNotFoundException:
        logger.info('thing_name: {}: shadow does not exist'.format(thing_name))
    except Exception as e:
        logger.error('thing_name: {}: delete_shadow: {}'.format(thing_name, e))
        raise DeviceReplicationGeneralException(e)


def delete_policy(c_iot, policy_name):
    logger.info('policy_name: {}'.format(policy_name))
    try:
        response = c_iot.list_targets_for_policy(policyName=policy_name, pageSize=10)
        targets = response['targets']
        logger.debug('targets: {}'.format(targets))

        if targets:
            logger.info(
                'policy_name: {}: targets attached, policy will not be deleted'.format(
                    policy_name
                )
            )
            return

        response = c_iot.list_policy_versions(policyName=policy_name)
        logger.info('policy_name: {} versions: {}'.format(
            policy_name, response['policyVersions']))

        for version in response["policyVersions"]:
            if not version['isDefaultVersion']:
                logger.info(
                    'policy_name: {} deleting policy version: {}'.format(
                        policy_name, version['versionId']
                    )
                )
                c_iot.delete_policy_version(policyName=policy_name,
                    policyVersionId=version['versionId'])
        logger.info('deleting policy: policy_name: {}'.format(policy_name))
        c_iot.delete_policy(policyName=policy_name)

    except c_iot.exceptions.ResourceNotFoundException:
        logger.info('policy_name: {}: does not exist'.format(policy_name))

    except Exception as e:
        logger.error('delete_policy: {}'.format(e))
        raise DeviceReplicationGeneralException(e)


def delete_thing(c_iot, thing_name, iot_data_endpoint):
    logger.info('delete_thing: thing_name: {} iot_data_endpoint: {}'.format(
        thing_name, iot_data_endpoint
        )
    )

    try:
        if not thing_exists(c_iot, thing_name):
            logger.warning('delete_thing: thing does not exist: {}'.format(thing_name))
            return

        r_principals = c_iot.list_thing_principals(thingName=thing_name)
        logger.info('thing_name: {} principals: {}'.format(thing_name, r_principals['principals']))

        for arn in r_principals['principals']:
            cert_id = arn.split('/')[-1]
            logger.info(
                'detach_thing_principal: thing_name: {} principal arn: {} cert_id: {}'.format(
                    thing_name, arn, cert_id
                )
            )

            r_detach_thing = c_iot.detach_thing_principal(thingName=thing_name, principal=arn)
            detach_thing_principal_status_code = \
            r_detach_thing['ResponseMetadata']['HTTPStatusCode']
            logger.info(
                'thing_name: {} arn: {} detach_thing_principal_status_code: {} \
                response detach_thing_principal: {}'.format(
                    thing_name, arn, detach_thing_principal_status_code, r_detach_thing
                )
            )

            if detach_thing_principal_status_code != 200:
                error_message = 'thing_name: {} arn: {} \
                detach_thing_principal_status_code not equal 200: {} '.format(
                    thing_name, arn, detach_thing_principal_status_code
                )
                logger.error(error_message)
                raise Exception(error_message)

            # still things attached to the principal?
            # If yes, don't deactivate cert or detach policies
            things = get_principal_things(c_iot, arn)
            if things:
                logger.info(
                    'still things {} attached to principal {} - \
                    certificate will not be inactvated, policies will not be removed'.format(
                        things, arn
                    )
                )
            else:
                logger.info('inactivate cert: thing_name: {} cert_id: {}'.format(
                    thing_name, cert_id))
                r_upd_cert = c_iot.update_certificate(certificateId=cert_id,newStatus='INACTIVE')
                logger.info('update_certificate: cert_id: {} response: {}'.format(
                    cert_id, r_upd_cert))

                r_policies = c_iot.list_principal_policies(principal=arn)
                logger.info('cert arn: {} policies: {}'.format(arn, r_policies['policies']))

                for policy in r_policies['policies']:
                    policy_name = policy['policyName']
                    logger.info('detaching policy policy_name: {}'.format(policy_name))
                    r_detach_pol = c_iot.detach_policy(policyName=policy_name,target=arn)
                    logger.info(
                        'detach_policy: policy_name: {} response: {}'.format(
                            policy_name, r_detach_pol
                        )
                    )
                    delete_policy(c_iot, policy_name)

                r_del_cert = c_iot.delete_certificate(certificateId=cert_id,forceDelete=True)
                logger.info('delete_certificate: cert_id: {} response: {}'.format(
                    cert_id, r_del_cert))

        r_del_thing = c_iot.delete_thing(thingName=thing_name)
        logger.info('delete_thing: thing_name: {} response: {}'.format(thing_name, r_del_thing))
        delete_shadow(thing_name, iot_data_endpoint)
    except Exception as e:
        logger.error('delete_thing: thing_name: {}: {}'.format(thing_name, e))
        raise DeviceReplicationDeleteThingException(e)


def update_thing(c_iot, c_iot_primary, thing_name, thing_type_name, attrs, merge):
    logger.info('update_thing: thing_name: {}'.format(thing_name))
    try:
        create_thing(c_iot, c_iot_primary, thing_name, "", {})

        if thing_type_name:
            create_thing_type(c_iot, thing_type_name)

            response = c_iot.update_thing(
                thingName=thing_name,
                thingTypeName=thing_type_name,
                attributePayload={
                    'attributes': attrs,
                    'merge': merge
                }
            )
        else:
            response = c_iot.update_thing(
                thingName=thing_name,
                attributePayload={
                    'attributes': attrs,
                    'merge': merge
                }
            )
        logger.info('update_thing: response: {}'.format(response))

    except Exception as e:
        logger.error('update_thing: {}'.format(e))
        raise DeviceReplicationUpdateThingException(e)


def delete_thing_create_error(c_dynamo, thing_name, table_name):
    logger.info('delete_thing_create_error: thing_name: {}'.format(thing_name))
    try:
        response = c_dynamo.delete_item(
            TableName=table_name,
            Key={'thing_name': {'S': thing_name}, 'action': {'S': 'create-thing'}}
        )
        logger.info('delete_thing_create_error: {}'.format(response))
    except Exception as e:
        logger.error("delete_thing_create_error: {}".format(e))
        raise DeviceReplicationGeneralException(e)
