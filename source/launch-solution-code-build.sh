#!/bin/bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

#
# launch-solution-code-build.sh
#

set -e

LAUNCH_VERSION="2021-02-10 01"
echo "LAUNCH_VERSION: $LAUNCH_VERSION"

DIR=$(pwd)

if [ -z "$BUCKET_RESOURCES" ]; then
  echo "BUCKET_RESOURCES is not defined, exiting"
  exit 1
fi

if [ -z "$SOLUTION_NAME" ]; then
  echo "SOLUTION_NAME is not defined, exiting"
  exit 1
fi

if [ -z "$VERSION" ]; then
  echo "VERSION is not defined, exiting"
  exit 1
fi

if [ "$CREATE_HEALTH_CHECK" != "yes" ]; then
  CREATE_HEALTH_CHECK=no
fi


echo "BUCKET_RESOURCES: $BUCKET_RESOURCES SOLUTION_NAME: $SOLUTION_NAME VERSION: $VERSION CREATE_HEALTH_CHECK: $CREATE_HEALTH_CHECK"

function dt () { date '+%Y-%m-%d %H:%M:%S'; }

START_DATE=$(dt)

if [ -z "$STACK_POSTFIX" ]; then
  echo "STACK_POSTFIX not defined creating STACK_POSTFIX"
  STACK_POSTFIX=$(date '+%Y%m%d%H%M%S')
  echo "new STACK_POSTFIX: $STACK_POSTFIX"
else
  echo "STACK_POSTFIX set already: $STACK_POSTFIX"
fi

if [ -z "$UUID" ]; then
  echo "UUID not defined creating UUID"
  UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
  echo "new UUID: $UUID"
else
  echo "UUID set already: $UUID"
fi


BUCKET_PRIMARY_REGION="iot-dr-primary-$UUID"
BUCKET_SECONDARY_REGION="iot-dr-secondary-$UUID"

echo "PRIMARY_REGION: $PRIMARY_REGION SECONDARY_REGION: $SECONDARY_REGION"
echo "BUCKET_PRIMARY_REGION: $BUCKET_PRIMARY_REGION BUCKET_SECONDARY_REGION: $BUCKET_SECONDARY_REGION"
ERROR=""

echo "$(dt): creating buckets"
aws s3 mb s3://$BUCKET_PRIMARY_REGION --region $PRIMARY_REGION

echo "$(dt) enabling encryption for bucket \"$BUCKET_PRIMARY_REGION\""
aws s3api put-bucket-encryption --region $PRIMARY_REGION \
    --bucket $BUCKET_PRIMARY_REGION \
    --server-side-encryption-configuration '{"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}'


aws s3 mb s3://$BUCKET_SECONDARY_REGION --region $SECONDARY_REGION

echo "$(dt) enabling encryption for bucket \"$BUCKET_SECONDARY_REGION\""
aws s3api put-bucket-encryption --region $SECONDARY_REGION \
    --bucket $BUCKET_SECONDARY_REGION \
    --server-side-encryption-configuration '{"Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}'

echo "$(dt): syncing jupyter to S3: $BUCKET_PRIMARY_REGION"
aws s3 sync jupyter s3://$BUCKET_PRIMARY_REGION/jupyter/

echo "$(dt): syncing tools to S3: $BUCKET_PRIMARY_REGION"
cp lambda/iot-dr-layer/device_replication.py tools/
aws s3 sync tools s3://$BUCKET_PRIMARY_REGION/tools/

echo "$(dt): syncing region syncers to S3: $BUCKET_PRIMARY_REGION"
aws s3 sync lambda s3://$BUCKET_PRIMARY_REGION/lambda/

echo "------------------------------"

touch toolsrc

DDB_TABLE_NAME="IoTDRGlobalTable${STACK_POSTFIX}"
IOT_ENDPOINT_PRIMARY=$(aws iot describe-endpoint --endpoint-type iot:Data-ATS --query 'endpointAddress' --region $PRIMARY_REGION --output text)
IOT_ENDPOINT_SECONDARY=$(aws iot describe-endpoint --endpoint-type iot:Data-ATS --query 'endpointAddress' --region $SECONDARY_REGION --output text)
echo "$(dt): IOT_ENDPOINT_PRIMARY: $IOT_ENDPOINT_PRIMARY IOT_ENDPOINT_SECONDARY: $IOT_ENDPOINT_SECONDARY"

#
# primary region
#
STACK_NAME="IoTDRPrimary${STACK_POSTFIX}"
CFN_TEMPLATE="${SOLUTION_NAME}/${VERSION}/disaster-recovery-for-aws-iot-primary-region.template"
TEMPLATE_URL=https://$BUCKET_RESOURCES.s3.amazonaws.com/$CFN_TEMPLATE
echo "$(dt): launching stack \"$STACK_NAME\" in region \"$PRIMARY_REGION\""
echo "  TEMPLATE_URL: $TEMPLATE_URL"
echo "  DDB_TABLE_NAME: $DDB_TABLE_NAME"
StackId=$(aws cloudformation create-stack \
  --stack-name $STACK_NAME \
  --template-url $TEMPLATE_URL \
  --parameters ParameterKey=GlobalDynamoDBTableName,ParameterValue=$DDB_TABLE_NAME \
  --capabilities CAPABILITY_IAM --region $PRIMARY_REGION --output text)

echo "StackId: $StackId"
echo "$(dt): waiting for stack \"$STACK_NAME\" to be created..."
aws cloudformation wait stack-create-complete \
  --stack-name $StackId \
  --region $PRIMARY_REGION
echo "$(dt): stack \"$STACK_NAME\" created"

echo "DDB table"
DDB_TABLE_NAME_PRIMARY=$(aws cloudformation describe-stack-resources \
  --stack-name $STACK_NAME \
  --region $PRIMARY_REGION \
  --query 'StackResources[?LogicalResourceId == `ProvisioningDynamoDBTable`].PhysicalResourceId' \
  --output text)
echo "DDB_TABLE_NAME_PRIMARY: $DDB_TABLE_NAME_PRIMARY"
echo "------------------------------"
BULK_PROVISIONING_ROLE_NAME=$(aws cloudformation describe-stack-resources --stack-name $STACK_NAME --region $PRIMARY_REGION --query 'StackResources[?LogicalResourceId==`IoTBulkProvisioningRole`][PhysicalResourceId]' --output text)
ARN_IOT_PROVISIONING_ROLE=$(aws iam get-role --role-name $BULK_PROVISIONING_ROLE_NAME --query 'Role.Arn' --output text)
echo "export ARN_IOT_PROVISIONING_ROLE=$ARN_IOT_PROVISIONING_ROLE" >> toolsrc


#
# secondary region
#
STACK_NAME="IoTDRSecondary${STACK_POSTFIX}"
CFN_TEMPLATE="${SOLUTION_NAME}/${VERSION}/disaster-recovery-for-aws-iot-secondary-region.template"
TEMPLATE_URL=https://$BUCKET_RESOURCES.s3.amazonaws.com/$CFN_TEMPLATE
echo "$(dt): launching stack \"$STACK_NAME\" in region \"$SECONDARY_REGION\""
echo "  TEMPLATE_URL: $TEMPLATE_URL"
echo "  DDB_TABLE_NAME: $DDB_TABLE_NAME"
StackId=$(aws cloudformation create-stack \
  --stack-name $STACK_NAME \
  --template-url $TEMPLATE_URL \
  --parameters ParameterKey=GlobalDynamoDBTableName,ParameterValue=$DDB_TABLE_NAME ParameterKey=Postfix,ParameterValue=$STACK_POSTFIX \
               ParameterKey=IoTEndpointPrimary,ParameterValue=$IOT_ENDPOINT_PRIMARY ParameterKey=IoTEndpointSecondary,ParameterValue=$IOT_ENDPOINT_SECONDARY \
  --capabilities CAPABILITY_IAM --region $SECONDARY_REGION --output text)

echo "StackId: $StackId"
echo "$(dt): waiting for stack \"$STACK_NAME\" to be created..."
aws cloudformation wait stack-create-complete \
  --stack-name $StackId \
  --region $SECONDARY_REGION
echo "$(dt): stack \"$STACK_NAME\" created"

echo "DDB table"
DDB_TABLE_NAME_SECONDARY=$(aws cloudformation describe-stack-resources \
  --stack-name $STACK_NAME \
  --region $SECONDARY_REGION \
  --query 'StackResources[?LogicalResourceId == `ProvisioningDynamoDBTable`].PhysicalResourceId' \
  --output text)
echo "DDB_TABLE_NAME_SECONDARY: $DDB_TABLE_NAME_SECONDARY"
echo "------------------------------"

#
# create global table
#
if [ "$DDB_TABLE_NAME_PRIMARY" != "$DDB_TABLE_NAME_SECONDARY" ]; then
  ERROR="($dt): ERROR: DynamoDB table names in primary and secondary region differ. Global table cannot be created."
else
  echo "$(dt): creating global DynamoDB table \"$DDB_TABLE_NAME_PRIMARY\""
  aws dynamodb create-global-table \
    --global-table-name $DDB_TABLE_NAME_PRIMARY \
    --replication-group RegionName=$PRIMARY_REGION RegionName=$SECONDARY_REGION \
    --region $PRIMARY_REGION
fi
sleep 2

GLOBAL_TABLE_STATUS=$(aws dynamodb describe-global-table --global-table-name $DDB_TABLE_NAME_PRIMARY --region $PRIMARY_REGION --query 'GlobalTableDescription.GlobalTableStatus' --output text)
echo "$(dt): GLOBAL_TABLE_STATUS: $GLOBAL_TABLE_STATUS"
while [ "$GLOBAL_TABLE_STATUS" != "ACTIVE" ]; do
  sleep 5
  GLOBAL_TABLE_STATUS=$(aws dynamodb describe-global-table --global-table-name $DDB_TABLE_NAME_PRIMARY --region $PRIMARY_REGION --query 'GlobalTableDescription.GlobalTableStatus' --output text)
  echo "$(dt): GLOBAL_TABLE_STATUS: $GLOBAL_TABLE_STATUS"
done


#
# R53 health checker primary region
#
STACK_NAME="R53HealthChecker${STACK_POSTFIX}"
CFN_TEMPLATE="${SOLUTION_NAME}/${VERSION}/disaster-recovery-for-aws-iot-r53-health-checker.template"
TEMPLATE_URL=https://$BUCKET_RESOURCES.s3.amazonaws.com/$CFN_TEMPLATE
echo "$(dt): launching stack \"$STACK_NAME\" in region \"$PRIMARY_REGION\""
echo "  TEMPLATE_URL: $TEMPLATE_URL"
StackId=$(aws cloudformation create-stack \
  --stack-name $STACK_NAME \
  --template-url $TEMPLATE_URL \
  --parameters ParameterKey=S3BucketForLambda,ParameterValue=$BUCKET_PRIMARY_REGION ParameterKey=CreateR53HealthCheck,ParameterValue=$CREATE_HEALTH_CHECK \
  --capabilities CAPABILITY_IAM --region $PRIMARY_REGION --output text)

echo "StackId: $StackId"
echo "$(dt): waiting for stack \"$STACK_NAME\" to be created..."
aws cloudformation wait stack-create-complete \
  --stack-name $StackId \
  --region $PRIMARY_REGION
echo "$(dt): stack \"$STACK_NAME\" created"
echo "------------------------------"

#
# R53 health checker secondary region
#
echo "Launching stack \"$STACK_NAME\" in region \"$SECONDARY_REGION\""
echo "  TEMPLATE_URL: $TEMPLATE_URL"
StackId=$(aws cloudformation create-stack \
  --stack-name $STACK_NAME \
  --template-url $TEMPLATE_URL \
  --parameters ParameterKey=S3BucketForLambda,ParameterValue=$BUCKET_SECONDARY_REGION ParameterKey=CreateR53HealthCheck,ParameterValue=$CREATE_HEALTH_CHECK \
  --capabilities CAPABILITY_IAM --region $SECONDARY_REGION --output text)

echo "StackId: $StackId"
echo "$(dt): waiting for stack \"$STACK_NAME\" to be created..."
aws cloudformation wait stack-create-complete \
  --stack-name $StackId \
  --region $SECONDARY_REGION
echo "$(dt): stack \"$STACK_NAME\" created"
echo "------------------------------"

echo "filling environment file"
echo "export IOT_ENDPOINT_PRIMARY=$IOT_ENDPOINT_PRIMARY" >> toolsrc
echo "export IOT_ENDPOINT_SECONDARY=$IOT_ENDPOINT_SECONDARY" >> toolsrc
echo "export REGION=$PRIMARY_REGION" >> toolsrc
echo "export S3_BUCKET=$BUCKET_PRIMARY_REGION" >> toolsrc
echo "export DYNAMODB_GLOBAL_TABLE=$DDB_TABLE_NAME_PRIMARY" >> toolsrc
echo "export PRIMARY_REGION=$PRIMARY_REGION" >> toolsrc
echo "export SECONDARY_REGION=$SECONDARY_REGION" >> toolsrc

aws s3 cp toolsrc s3://$BUCKET_PRIMARY_REGION/tools/toolsrc

END_DATE=$(dt)
echo "START_DATE: $START_DATE"
echo "END_DATE: $END_DATE"
 if [ ! -z "$ERROR" ]; then
  echo "errors encountered: $ERROR"
  exit 1
fi
exit 0
