#!/bin/bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# run-tests.sh


usage() {
  echo "Usage: $0 -b thing_basename -d devices_dir" 1>&2
  exit 1
}

while getopts ":b:d:" options; do
  case "${options}" in
    b)
      THING_BASENAME=${OPTARG}
      ;;
    d)
      DEVICES_DIR=${OPTARG}
      ;;
    :)
      echo "Error: -${OPTARG} requires an argument."
      usage
      ;;
    *)
      usage
      ;;
  esac
done

[ -z "$DEVICES_DIR" ] && usage
[ -z "$THING_BASENAME" ] && usage

DIR=$(dirname $(realpath $0))
test ! -e $DIR/toolsrc && exit 1
. $DIR/toolsrc

echo "DIR: $DIR"
echo "THING_BASENAME: $THING_BASENAME: DEVICES_DIR: $DEVICES_DIR"
cd $DEVICES_DIR || exit 2

NUM_THINGS=$(ls -1 *.key | wc -l)
echo "NUM_THINGS: $NUM_THINGS"

curl https://www.amazontrust.com/repository/AmazonRootCA1.pem -o root.ca.pem

NUM_TESTS=2
[ "$NUM_THINGS" -ge 100 ] && NUM_TESTS=5
[ "$NUM_THINGS" -ge 1000 ] && NUM_TESTS=10

echo "NUM_TESTS: $NUM_TESTS"
cp /dev/null randoms
for i in $(seq 1 $NUM_TESTS); do
    echo $((1 + $RANDOM % $NUM_THINGS)) >> randoms
    sleep 1
done

for n in $(cat randoms); do
  thing_name=${THING_BASENAME}${n}
  key=$thing_name.key
  cert=$thing_name.crt
  echo "RANDOM: thing_name: $thing_name IOT_ENDPOINT_PRIMARY: $IOT_ENDPOINT_PRIMARY IOT_ENDPOINT_SECONDARY: $IOT_ENDPOINT_SECONDARY" | tee -a ../randoms.log
  
  echo $DIR/iot-dr-pubsub.py --cert $cert --key $key --root-ca root.ca.pem --count 3 --interval 1 --endpoint $IOT_ENDPOINT_PRIMARY | tee -a ../randoms.log
  $DIR/iot-dr-pubsub.py --cert $cert --key $key --root-ca root.ca.pem --count 3 --interval 1 --endpoint $IOT_ENDPOINT_PRIMARY | tee ../${thing_name}-primary.log
  
  echo $DIR/iot-dr-pubsub.py --cert $cert --key $key --root-ca root.ca.pem --count 3 --interval 1 --endpoint $IOT_ENDPOINT_SECONDARY | tee -a ../randoms.log
  $DIR/iot-dr-pubsub.py --cert $cert --key $key --root-ca root.ca.pem --count 3 --interval 1 --endpoint $IOT_ENDPOINT_SECONDARY | tee ../${thing_name}-secondary.log
done
cd ..
