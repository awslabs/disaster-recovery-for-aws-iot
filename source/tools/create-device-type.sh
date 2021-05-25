#!/bin/bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#
# create-device.sh - provision a device with AWS IoT Core
#

if [ -z $1 ]; then
    echo "usage: $0 <thing_name>"
    exit 1
fi

THING_NAME=$1

POLICY_NAME=""
test ! -z $2 && POLICY_NAME=$2 


echo "Provisioning thing \"$THING_NAME\" in AWS IoT Core..."

if aws iot describe-thing --thing-name $THING_NAME > /dev/null 2>&1; then 
    echo "ERROR: device exists already. Exiting..."; 
    aws iot describe-thing --thing-name $THING_NAME
    exit 1
fi

TMP_FILE=$(mktemp)

echo "  create thing"
aws iot create-thing --thing-name $THING_NAME --thing-type-name dr-type03

echo "  create device key and certificate"
aws iot create-keys-and-certificate --set-as-active \
  --public-key-outfile $THING_NAME.public.key \
  --private-key-outfile $THING_NAME.private.key \
  --certificate-pem-outfile $THING_NAME.certificate.pem > $TMP_FILE

CERTIFICATE_ARN=$(jq -r ".certificateArn" $TMP_FILE)
CERTIFICATE_ID=$(jq -r ".certificateId" $TMP_FILE)
echo "  certificate arn: $CERTIFICATE_ARN"
echo "  echo certificate id: $CERTIFICATE_ID"

if [ -z $POLICY_NAME ]; then
    POLICY_NAME=${THING_NAME}_Policy
    echo "  create IoT policy \"$POLICY_NAME\""
    aws iot create-policy --policy-name $POLICY_NAME \
      --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action": "iot:*","Resource":"*"}]}'
else
    echo "using provided policy \"$POLICY_NAME\""
fi

sleep 10

echo "  attach policy to certificate"
aws iot attach-policy --policy-name $POLICY_NAME \
  --target $CERTIFICATE_ARN

sleep 10

echo "  attach certificate to thing"
aws iot attach-thing-principal --thing-name $THING_NAME \
  --principal $CERTIFICATE_ARN
  
rm $TMP_FILE
