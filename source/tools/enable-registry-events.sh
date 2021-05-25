#!/bin/bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# Check to see if input has been provided:
if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ]; then
    echo "Please provide the root-region name, primary region & secondary region"
    echo "For example: ./enable-registry-events.sh us-east-1 eu-central-1 eu-west-1"
    exit 1
fi
REGIONS=($1 $2 $3)
for region in "${!REGIONS[@]}";
  do
    echo "enabling registry events & indexing in:" ${REGIONS[region]}
    IND=$(aws iot update-indexing-configuration --region ${REGIONS[region]} --thing-indexing-configuration 'thingIndexingMode=REGISTRY_AND_SHADOW,thingConnectivityIndexingMode=STATUS')
    REG=$(aws iot update-event-configurations --region ${REGIONS[region]} --cli-input-json '{"eventConfigurations": {"THING_TYPE": {"Enabled": true},"JOB_EXECUTION": {"Enabled": true},"THING_GROUP_HIERARCHY": {"Enabled": true},"CERTIFICATE": {"Enabled": true},"THING_TYPE_ASSOCIATION": {"Enabled": true},"THING_GROUP_MEMBERSHIP": {"Enabled": true},"CA_CERTIFICATE": {"Enabled": true},"THING":{"Enabled": true},"JOB": {"Enabled": true},"POLICY": {"Enabled": true},"THING_GROUP": {"Enabled": true}}}');
done