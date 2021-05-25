#!/bin/bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

set -e

echo "building lambda installation packages"
cd lambda

cd iot-mr-jitr
pip install pyOpenSSL -t .
cd ..

for lambda in iot-mr-jitr iot-mr-cross-region \
  sfn-iot-mr-dynamo-trigger  sfn-iot-mr-thing-crud \
  sfn-iot-mr-thing-group-crud sfn-iot-mr-thing-type-crud \
  sfn-iot-mr-shadow-syncer \
  iot-dr-missing-device-replication
do
  echo "  creating zip for \"$lambda\""
  rm -f ${lambda}.zip
  cd $lambda
  python -m py_compile *.py
  rm -rf __pycache__
  zip ../${lambda}.zip -r .
  cd ..
done

# layer
echo "creating lambda layer installation package"
cd iot-dr-layer
rm -rf python
mkdir python
pip install dynamodb-json==1.3 --no-deps -t python
pip install simplejson==3.17.2 -t python
python -m py_compile device_replication.py
rm -rf __pycache__
cp device_replication.py python/

rm -f ../iot-dr-layer.zip
zip ../iot-dr-layer.zip -r python
cd ..

echo "ZIP files:"
pwd
ls -l *.zip
