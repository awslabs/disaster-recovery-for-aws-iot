#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

import json
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    logger.info("context: {}".format(context))
    logger.info("event: {}".format(event))
    # TODO implement
    return {
        'statusCode': 200,
        'body': json.dumps({"return": "message"})
    }
