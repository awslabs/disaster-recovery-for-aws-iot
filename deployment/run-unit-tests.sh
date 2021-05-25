#!/bin/bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This assumes all of the OS-level configuration has been completed and git repo has already been cloned
#
# This script should be run from the repo's deployment directory
# cd deployment
# ./run-unit-tests.sh
#

set -e
# Get reference for all important folders
template_dir="$PWD"
source_dir="$template_dir/../source"

echo "------------------------------------------------------------------------------"
echo "[Init] Unit tests"
echo "------------------------------------------------------------------------------"

cd $source_dir/lambda

echo "python version: $(python3 --version)"

for lambda in iot-mr-jitr iot-mr-cross-region \
  sfn-iot-mr-dynamo-trigger  sfn-iot-mr-thing-crud \
  sfn-iot-mr-thing-group-crud sfn-iot-mr-thing-type-crud \
  sfn-iot-mr-shadow-syncer \
  iot-dr-missing-device-replication \
  iot-dr-create-r53-checker \
  iot-dr-launch-solution \
  iot-dr-layer
do
  echo "py_compile for \"$lambda\""
  cd $lambda
  python3 -m py_compile *.py
  rm -rf __pycache__
  cd ..
done
