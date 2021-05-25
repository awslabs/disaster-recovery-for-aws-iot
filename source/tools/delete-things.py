#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.

# delete-things.py
#
# deletes things given by query string

"""Script to delete things from the device registry
of IoT Core matched by a given query string."""

import argparse
import logging
import sys
import time

import boto3
import boto3.session

from device_replication import delete_thing

logger = logging.getLogger()
for h in logger.handlers:
    logger.removeHandler(h)
h = logging.StreamHandler(sys.stdout)
FORMAT = '%(asctime)s [%(levelname)s]: \
%(threadName)s-%(filename)s:%(lineno)s-%(funcName)s: %(message)s'
h.setFormatter(logging.Formatter(FORMAT))
logger.addHandler(h)
logger.setLevel(logging.INFO)
#logger.setLevel(logging.DEBUG)

parser = argparse.ArgumentParser(description="Delete things matching a given query string.")
parser.add_argument('--region', required=True, help="AWS region.")
parser.add_argument(
    '--query-string', required=True,
    help="Query string for example 'thingName:my-devices*'"
)
parser.add_argument(
    '--retries', type=int, default=5,
    help="Number of retries in case of delete failure, default 5."
)
parser.add_argument('--wait', type=int, default=1, help="Wait between retries, default 1.")
parser.add_argument('-f', action='store_true', help="When true force delete without request.")
args = parser.parse_args()

NUM_THINGS_DELETED = 0
POLICY_NAMES = {}
THING_NAMES = []
NUM_ERRORS = 0

session = boto3.session.Session(region_name=args.region)
c_iot = session.client('iot', region_name=args.region)
iot_data_endpoint = c_iot.describe_endpoint(endpointType='iot:Data-ATS')['endpointAddress']

logger.info("query_string: %s region: %s", args.query_string, args.region)
logger.info("iot_data_endpoint: %s", iot_data_endpoint)

response = c_iot.search_index(queryString=args.query_string)

logger.info("response:\n%s", response)
for thing in response["things"]:
    THING_NAMES.append(thing["thingName"])

while 'nextToken' in response:
    next_token = response['nextToken']
    logger.info("next token: %s", next_token)
    response = c_iot.search_index(
        queryString=args.query_string,
        nextToken=next_token
    )
    logger.info("response:\n%s", response)
    for thing in response["things"]:
        THING_NAMES.append(thing["thingName"])

if not THING_NAMES:
    logger.info("no things found matching query_string: %s", args.query_string)
    sys.exit(0)

NUM_THINGS = len(THING_NAMES)

if args.f is False:
    print("--------------------------------------\n")
    print("thing names to be DELETED:\n{}\n".format(THING_NAMES))
    print("number of things to delete: {}\n".format(NUM_THINGS))
    print("--------------------------------------\n")
    input("{} DEVICES FROM THE LIST ABOVE WILL BE DELETED \
    INCLUDING CERTIFICATES, POLICIES AND SHADOWS \
    \n== press <enter> to continue, <ctrl+c> to abort!\n".format(NUM_THINGS))
else:
    logger.info("-f is set - deleting without request: NUM_THINGS: %s", NUM_THINGS)
    time.sleep(1)


for thing_name in THING_NAMES:
    THING_DELETED = False
    retries = args.retries
    wait = args.wait
    i = 1
    while THING_DELETED is False and i <= retries:
        try:
            logger.info("%s: THING NAME: %s", i, thing_name)
            i += 1
            delete_thing(c_iot, thing_name, iot_data_endpoint)
            THING_DELETED = True
            NUM_THINGS_DELETED += 1
            time.sleep(0.1) # avoid to run into api throttling
            break
        except Exception as delete_error:
            logger.error("delete thing thing_name: %s: %s", thing_name, delete_error)
            NUM_ERRORS += 1

        time.sleep(wait*i)


logger.info("stats: NUM_THINGS: %s NUM_THINGS_DELETED: %s NUM_ERRORS: %s",
        NUM_THINGS, NUM_THINGS_DELETED, NUM_ERRORS
)
