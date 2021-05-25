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

if [ -z $PCA_ARN ]; then
    echo "environment varriable PCA_ARN not set"
    echo "set it with export PCA_ARN=<ARN_OF_YOUR_PCA>"
    exit 1
fi

PCA_REGION=$(echo $PCA_ARN |awk -F ':' '{print $4}')

echo "Provisioning thing \"$THING_NAME\" in AWS IoT Core with certificate from PCA..."
echo "  PCA_ARN: $PCA_ARN"
echo "  PCA_REGION=$PCA_REGION"
sleep 1

if aws iot describe-thing --thing-name $THING_NAME > /dev/null 2>&1; then 
    echo "ERROR: device exists already. Exiting..."; 
    aws iot describe-thing --thing-name $THING_NAME
    exit 1
fi

TMP_FILE=$(mktemp)

echo "requesting certificate from PCA: $PCA_ARN"
openssl req -nodes -new -newkey rsa:2048 -keyout $THING_NAME.private.key -out $THING_NAME.csr -subj "/CN=$THING_NAME"
CERTIFICATE_ARN_PCA=$(aws acm-pca issue-certificate --certificate-authority-arn $PCA_ARN --csr file://./$THING_NAME.csr --signing-algorithm "SHA256WITHRSA" --validity Value=365,Type="DAYS" --region $PCA_REGION | jq -r '.CertificateArn')
echo "CERTIFICATE_ARN_PCA: $CERTIFICATE_ARN_PCA"
aws acm-pca wait certificate-issued --certificate-authority-arn $PCA_ARN --certificate-arn $CERTIFICATE_ARN_PCA --region $PCA_REGION
aws acm-pca get-certificate --certificate-authority-arn $PCA_ARN --certificate-arn $CERTIFICATE_ARN_PCA --region $PCA_REGION > $TMP_FILE
jq -r '.Certificate' $TMP_FILE > $THING_NAME.certificate.pem

echo "Provisioning thing \"$THING_NAME\" in AWS IoT Core..."

echo "  create thing"
aws iot create-thing --thing-name $THING_NAME

if [ -z $POLICY_NAME ]; then
    POLICY_NAME=${THING_NAME}_Policy
    echo "  create IoT policy \"$POLICY_NAME\""
    aws iot create-policy --policy-name $POLICY_NAME \
      --policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action": "iot:*","Resource":"*"}]}'
else
    echo "using provided policy \"$POLICY_NAME\""
fi

sleep 10

echo "  register certificate without CA"
CERTIFICATE_ARN=$(aws iot register-certificate-without-ca --certificate-pem file://./$THING_NAME.certificate.pem --status ACTIVE | jq -r '.certificateArn')
echo "  CERTIFICATE_ARN: $CERTIFICATE_ARN"
echo "  attach policy to certificate"
aws iot attach-policy --policy-name $POLICY_NAME --target $CERTIFICATE_ARN

sleep 10

echo "  attach certificate to thing"
aws iot attach-thing-principal --thing-name $THING_NAME --principal $CERTIFICATE_ARN
  
rm $TMP_FILE
