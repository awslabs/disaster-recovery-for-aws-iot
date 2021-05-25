#!/bin/bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# iot-dr-run-tests.sh


usage() {
  echo "Usage: $0 -n number_of_things [ -b thing_basename ]" 1>&2
  exit 1
}

log() {
  echo "$(date +'%Y-%m-%d %H:%M:%S'): ${@}" | tee -a iot-dr-run-tests.log
}

while getopts ":n:b:" options; do
  case "${options}" in
    n)
      NUM_THINGS=${OPTARG}
      re_isanum='^[0-9]+$'
      if ! [[ $NUM_THINGS =~ $re_isanum ]]; then
        echo "Error: number_of_things must be a positive, whole number."
        usage
      elif [ $NUM_THINGS -eq "0" ]; then
        echo "Error: number_of_things must be greater than zero."
        usage
      fi
      ;;
    b)
      THING_BASENAME=${OPTARG}
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

UUID=$(uuid)
[ -z "$NUM_THINGS" ] && usage
[ -z "$PRIMARY_REGION" ] && echo "shell variable PRIMARY_REGION not set" && exit 2
[ -z "$SECONDARY_REGION" ] && echo "shell variable SECONDARY_REGION not set" && exit 2
[ -z "$IOT_ENDPOINT_PRIMARY" ] && echo "shell variable IOT_ENDPOINT_PRIMARY not set" && exit 2
[ -z "$IOT_ENDPOINT_SECONDARY" ] && echo "shell variable IOT_ENDPOINT_SECONDARY not set" && exit 2

THING_INDEXING_PRIMARY=$(aws iot get-indexing-configuration --query 'thingIndexingConfiguration.thingIndexingMode' --region $PRIMARY_REGION --output text)
[ "$THING_INDEXING_PRIMARY" == "OFF" ] && echo "thing indexing not enabled in region $PRIMARY_REGION" && exit 3

THING_INDEXING_SECONDARY=$(aws iot get-indexing-configuration --query 'thingIndexingConfiguration.thingIndexingMode' --region $SECONDARY_REGION --output text)
[ "$THING_INDEXING_SECONDARY" == "OFF" ] && echo "thing indexing not enabled in region $SECONDARY_REGION" && exit 3


[ -z "$THING_BASENAME" ] && THING_BASENAME="dr-test-${UUID}-"
QUERY_STRING="thingName:${THING_BASENAME}*"
POLICY_NAME="dr-test-${UUID}_Policy"
TEMPLATE_BODY="dr-test-${UUID}_templateBody.json"

DIR=$(dirname $(realpath $0))
echo "DIR: $DIR"
test ! -e $DIR/toolsrc && exit 1
. $DIR/toolsrc

for region in $PRIMARY_REGION $SECONDARY_REGION; do
  echo "CHECK if a thing exists in region $region for query string $QUERY_STRING"
  thing_exists=$(aws iot search-index --query-string $QUERY_STRING --query 'things' --output text --max-results 1 --region $region)
  if [ ! -z "$thing_exists" ]; then
    echo "ERROR: thing with basename ${THING_BASENAME}* already exist in region $region"
    echo "  Thing: $thing_exists"
    echo "  Please choose another basename"
    echo "  QUERY_STRING \"$QUERY_STRING\" may not match any existing devices"
    exit 1
  else
    echo "no thing found"
  fi
done

START_TIME=$(date +%s)

DATE_TIME=$(date "+%Y-%m-%d_%H-%M-%S")
TEST_DIR=iot-dr-test-results-${DATE_TIME}
if [ -d $TEST_DIR ]; then
  echo "TEST_DIR \"$TEST_DIR\" exists, exiting"
  exit 1
else
  mkdir $TEST_DIR
fi

cd $TEST_DIR

log "THING_BASENAME: $THING_BASENAME"
log "NUM_THINGS: $NUM_THINGS" 
log "QUERY_STRING: \"$QUERY_STRING\""
log "POLICY_NAME: POLICY_NAME"
log "TEMPLATE_BODY: $TEMPLATE_BODY"
log "test results will be stored in directory $TEST_DIR"
sleep 2

cp /dev/null testrc
echo "THING_BASENAME=$THING_BASENAME" >> testrc
echo "NUM_THINGS=$NUM_THINGS" >> testrc
echo "QUERY_STRING=$QUERY_STRING" >> testrc
echo "POLICY_NAME=$POLICY_NAME" >> testrc

log "CREATE POLICY and TEMPLATE BODY"
ACCOUNT_ID=$(aws sts get-caller-identity --query 'Account' --output text)
sed -e "s/AWS_REGION/$PRIMARY_REGION/g" -e "s/AWS_ACCOUNT_ID/$ACCOUNT_ID/g" $DIR/policyBulk.json.in > ${POLICY_NAME}.json
sed -e "s/__POLICY_NAME__/$POLICY_NAME/g" $DIR/simpleTemplateBody2.json.in > $TEMPLATE_BODY
AWS_PAGER="" aws iot create-policy --policy-name $POLICY_NAME --policy-document file://${POLICY_NAME}.json --region $PRIMARY_REGION
CWD=$(pwd)
echo "$CWD/$TEMPLATE_BODY"

log "CREATE - THING_BASENAME: $THING_BASENAME NUM_THINGS: $NUM_THINGS"
log AWS_DEFAULT_REGION=$PRIMARY_REGION $DIR/bulk-bench.sh $THING_BASENAME $NUM_THINGS "$CWD/$TEMPLATE_BODY"
AWS_DEFAULT_REGION=$PRIMARY_REGION $DIR/bulk-bench.sh $THING_BASENAME $NUM_THINGS "$CWD/$TEMPLATE_BODY" | tee bulk-bench.log

log "things created, waiting a minute for replication..."
sleep 60

log "SHADOW COMPARE"
log $DIR/iot-dr-shadow-cmp.py --primary-region $PRIMARY_REGION --secondary-region $SECONDARY_REGION --num-tests $NUM_THINGS
$DIR/iot-dr-shadow-cmp.py --primary-region $PRIMARY_REGION --secondary-region $SECONDARY_REGION --num-tests $NUM_THINGS | tee iot-dr-shadow-cmp.log

log "PUB/SUB RANDOMS"
DEVICES_DIR=$(find . -type d -name "$THING_BASENAME*")
log $DIR/iot-dr-random-tests.sh -b $THING_BASENAME -d $DEVICES_DIR
$DIR/iot-dr-random-tests.sh -b $THING_BASENAME -d $DEVICES_DIR | tee iot-dr-random-tests.log


log "COMPARE - QUERY_STRING: $QUERY_STRING"
log $DIR/iot-devices-cmp.py --primary-region $PRIMARY_REGION --secondary-region $SECONDARY_REGION --query-string "$QUERY_STRING"
$DIR/iot-devices-cmp.py --primary-region $PRIMARY_REGION --secondary-region $SECONDARY_REGION --query-string "$QUERY_STRING" | tee iot-devices-cmp.log
sleep 5

log "DELETE - QUERY_STRING: $QUERY_STRING"
log AWS_DEFAULT_REGION=$PRIMARY_REGION $DIR/delete-things.py --region $PRIMARY_REGION --query-string "$QUERY_STRING" -f
AWS_DEFAULT_REGION=$PRIMARY_REGION $DIR/delete-things.py --region $PRIMARY_REGION --query-string "$QUERY_STRING" -f | tee delete-things.log

log "Waiting a minute for index to be updated..."
sleep 60

log "ALL TESTS FINISHED"
log "--------------------------------------------------------------"

log "TEST IF ALL THINGS DELETED"
AWS_PAGER="" AWS_DEFAULT_REGION=$PRIMARY_REGION aws iot search-index --query-string "$QUERY_STRING" --query 'things' --output text | tee things-in-$PRIMARY_REGION.log
AWS_PAGER="" AWS_DEFAULT_REGION=$SECONDARY_REGION aws iot search-index --query-string "$QUERY_STRING" --query 'things' --output text | tee things-in-$SECONDARY_REGION.log

if [ -s things-in-$PRIMARY_REGION.log ]; then
  log "NOT all things deleted in PRIMARY_REGION: $PRIMARY_REGION: QUERY_STRING: $QUERY_STRING"
  log "see: things-in-$PRIMARY_REGION.log"
else
  log "ALL things deleted in PRIMARY_REGION: $PRIMARY_REGION: QUERY_STRING: $QUERY_STRING"
fi

if [ -s things-in-$SECONDARY_REGION.log ]; then
  log "NOT all things deleted in SECONDARY_REGION: $SECONDARY_REGION: QUERY_STRING: $QUERY_STRING"
  log "see: things-in-$SECONDARY_REGION.log"
else
  log "ALL things deleted in SECONDARY_REGION: $SECONDARY_REGION: QUERY_STRING: $QUERY_STRING"
fi
log "--------------------------------------------------------------"

log "ERRORS IN LOGS"
grep -i error *.log|egrep -v 'no errors detected|TYPE ERRORS'
log "--------------------------------------------------------------"


END_TIME=$(date +%s)
DURATION=$(expr $END_TIME - $START_TIME)
log "AWS IoT DR test stats"
log "--------------------------------------------------------------"
log "THING_BASENAME: $THING_BASENAME"
log "NUM_THINGS: $NUM_THINGS"
log "QUERY_STRING: $QUERY_STRING"
log "START: $(date -d@$START_TIME +'%Y-%m-%d %H:%M:%S')"
log "END: $(date -d@$END_TIME +'%Y-%m-%d %H:%M:%S')"
log "DURATION: $DURATION secs."
log "RESULTS in directory \"$TEST_DIR\""

cd ..
