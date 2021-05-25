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

if [ -z $REGION ]; then
    echo "set the variable REGION to your aws region"
    exit 1
fi

THING_NAME=$1

POLICY_NAME=""
test ! -z $2 && POLICY_NAME=$2 

ACCOUNT_ID=$(aws sts get-caller-identity --output text |awk '{print $1}')

echo "Provisioning thing \"$THING_NAME\" in AWS IoT Core..."

if aws iot describe-thing --thing-name $THING_NAME > /dev/null 2>&1; then 
    echo "ERROR: device exists already. Exiting..."; 
    aws iot describe-thing --thing-name $THING_NAME
    exit 1
fi

TMP_FILE=$(mktemp)
POL_FILE=$(mktemp)

DIR=$(dirname $0)

if [ -z "$AWS_DEFAULT_REGION" ]; then
    sed -e "s/AWS_REGION/$REGION/" -e "s/AWS_ACCOUNT_ID/$ACCOUNT_ID/" $DIR/sample-pol1.json > $POL_FILE
else
    sed -e "s/AWS_REGION/$AWS_DEFAULT_REGION/" -e "s/AWS_ACCOUNT_ID/$ACCOUNT_ID/" $DIR/sample-pol1.json > $POL_FILE
fi

echo "  create thing"
aws iot create-thing --thing-name $THING_NAME

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
    #aws iot create-policy --policy-name $POLICY_NAME \
    #  --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action": "iot:*","Resource":"*"}]}'
    aws iot create-policy --policy-name $POLICY_NAME --policy-document file://$POL_FILE
    
else
    echo "using provided policy \"$POLICY_NAME\""
fi

sleep 1

echo "  attach policy to certificate"
aws iot attach-policy --policy-name $POLICY_NAME \
  --target $CERTIFICATE_ARN

sleep 1

echo "  attach certificate to thing"
aws iot attach-thing-principal --thing-name $THING_NAME \
  --principal $CERTIFICATE_ARN
  
rm $TMP_FILE
rm $POL_FILE
