#!/bin/bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

IMG="iot-dr-region-syncer"
TAG="$(date '+%Y-%m-%d_%H-%M-%S')"
ECR="AWS_ACCOUNT.dkr.ecr.AWS_REGION.amazonaws.com/iot-dr-region-syncer"

echo "building docker image \"$TAG\""

cp ../iot-dr-layer/device_replication.py .

docker build --no-cache --tag $IMG:$TAG .

echo "tagging for ECR"
docker tag $IMG:$TAG $ECR:$TAG

echo "ecr login"
aws ecr get-login-password \
    --region eu-west-2 \
| docker login \
    --username AWS \
    --password-stdin AWS_ACCOUNT.dkr.ecr.AWS_REGION.amazonaws.com

echo "push image"
docker push $ECR:$TAG

echo "For Fargate"
echo "-----------"
echo "${IMG}_${TAG}"
echo "$ECR:$TAG"
