#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.

import boto3
import json
import sys

THING_NAME=None
try:
    THING_NAME=sys.argv[1]
except IndexError:
    print('usage: {} <thing_name>'.format(sys.argv[0]))
    sys.exit(1)


c_iot = boto3.client('iot')

def print_response(response):
    del response['ResponseMetadata']
    print(json.dumps(response, indent=2, default=str))
    

try:
    response = c_iot.describe_thing(thingName=THING_NAME)
    print('THING')
    print_response(response)
    print('----------------------------------------')
    
    response = c_iot.list_thing_principals(thingName=THING_NAME)
    
    for principal in response['principals']:
        print('PRINCIPAL: {}'.format(principal))
        response = c_iot.describe_certificate(certificateId=principal.split('/')[-1])
        print('CERTIFICATE')
        print('  creationDate: {}'.format(response['certificateDescription']['creationDate']))
        print('  validity: {}'.format(response['certificateDescription']['validity']))
        print('  certificateMode: {}'.format(response['certificateDescription']['certificateMode']))
        print('----------------------------------------')
        
        response = c_iot.list_principal_policies(principal=principal)
        print('POLICIES')
        
        for policy in response['policies']:
            response = c_iot.get_policy(policyName=policy['policyName'])
            print_response(response)
except Exception as e:
    print('ERROR: {}'.format(e))