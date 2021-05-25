#!/bin/bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# bulk-bench.sh
# shell script for doing a very basic benchmark
# for bulk provisioing

DIR=$(dirname $0)
REAL_DIR=$(dirname $(realpath $0))

if [ -z $1 ] || [ -z $2 ]; then
    echo "usage: $0 <base_thingname> <num_things> [<template_body>]"
    exit 1
fi

THING_BASENAME=$1
NUM_THINGS=$2
TEMPLATE_BODY="${REAL_DIR}/simpleTemplateBody.json"
if [ ! -z "$3" ]; then
    TEMPLATE_BODY=$3
fi

if [ -z "$S3_BUCKET" ]; then
    echo "you must set the shell variable S3_BUCKET to a bucket where you have write permissions to"
    echo "an S3 bucket is required for bulk provisioing"
    exit 1
fi

if [ -z "$ARN_IOT_PROVISIONING_ROLE" ]; then
    echo "you must set the shell variable ARN_IOT_PROVISIONING_ROLE to the arn of an IAM role"
    echo "which allows bulk provisioning devices in your account"
    exit 1
fi

if [ ! -e $TEMPLATE_BODY ]; then
    echo "cannot find provisioning template \"$TEMPLATE_BODY\""
    exit 1
fi


DATE_TIME=$(date "+%Y-%m-%d_%H-%M-%S")
BULK_JSON="bulk-${DATE_TIME}.json"

OUT_DIR=${THING_BASENAME}-${DATE_TIME}
mkdir $OUT_DIR || exit 1

echo "starting bulk provisioning..."
echo "THING_BASENAME: \"$THING_BASENAME\" NUM_THINGS: \"$NUM_THINGS\""
echo "TEMPLATE_BODY: \"$TEMPLATE_BODY\""
echo "OUT_DIR: \"$OUT_DIR\" BULK_JSON: \"$BULK_JSON\""

sleep 2

TIME_START_GEN_KEYS=$(date +%s)
cp /dev/null $OUT_DIR/$BULK_JSON
for i in $(seq 1 $NUM_THINGS) ; do
    thing_name=${THING_BASENAME}${i}
    echo "${i}/${NUM_THINGS}: creating key/csr for \"$thing_name\""
    openssl req -new -newkey rsa:2048 -nodes -keyout $OUT_DIR/${thing_name}.key -out $OUT_DIR/${thing_name}.csr -subj "/C=DE/ST=Berlin/L=Berlin/O=AWS/CN=${thing_name}"
    
    one_line_csr=$(awk 'NF {sub(/\r/, ""); printf "%s\\n",$0;}' $OUT_DIR/${thing_name}.csr)
    
    echo "{\"ThingName\": \"${thing_name}\", \"SerialNumber\": \"$i\", \"CSR\": \"$one_line_csr\"}" >> $OUT_DIR/$BULK_JSON
done

TIME_END_GEN_KEYS=$(date +%s)
TIME_TOTAL_GEN_KEYS=$(expr $TIME_END_GEN_KEYS - $TIME_START_GEN_KEYS)

echo "output written to $OUT_DIR/$BULK_JSON"

echo "copying $OUT_DIR/$BULK_JSON to s3://$S3_BUCKET/"
aws s3 cp $OUT_DIR/$BULK_JSON s3://$S3_BUCKET/
aws s3 ls s3://$S3_BUCKET/

TEMP_FILE=$(mktemp)
echo "TEMP_FILE: $TEMP_FILE"

TIME_START_BULK=$(date +%s)
aws iot start-thing-registration-task \
  --template-body file://$TEMPLATE_BODY \
  --input-file-bucket $S3_BUCKET \
  --input-file-key $BULK_JSON --role-arn $ARN_IOT_PROVISIONING_ROLE | tee $TEMP_FILE

task_id=$(jq -r ".taskId" $TEMP_FILE)
echo "task_id: $task_id"


rc=1
rc_err=1
TEMP_FILE2=$(mktemp)
echo "TEMP_FILE2: $TEMP_FILE2"
while [[ $rc -ne 0 && $rc_err -ne 0 ]]; do
    echo "$(date '+%Y-%m-%d_%H-%M-%S'): task_id: $task_id"
    #echo "RESULTS"
    aws iot list-thing-registration-task-reports --report-type RESULTS --task-id $task_id | tee $TEMP_FILE2
    url=$(jq -r '.resourceLinks[]' $TEMP_FILE2)
    echo $url | grep ^https
    rc=$?
    echo "TYPE RESULTS list-thing-registration-task-reports: rc: $rc"
    if [ $rc -eq 0 ]; then
        echo "  downloading results to $OUT_DIR/results.json"
        wget -O $OUT_DIR/results.json "$url"
        echo "  results written to: $OUT_DIR/results.json"
    else
        echo "  no results yet"
    fi

    #echo "ERRORS"
    err_url=$(aws iot list-thing-registration-task-reports --report-type ERRORS --task-id $task_id | jq -r '.resourceLinks[]')
    echo $err_url | grep -q '^https'
    rc_err=$?
    echo "TYPE ERRORS list-thing-registration-task-reports: rc_err: $rc_err"
    if [ $rc_err -eq 0 ]; then
        echo "  errors detected, downloading to $OUT_DIR/errors.json"
        wget -O $OUT_DIR/errors.json "$err_url"
        echo "  errors written to: $OUT_DIR/errors.json"
        echo "ERRORS detected!!! Consider stopping with Ctrl+C and analyse errors"
        sleep 5
    else
        echo "  no errors detected"
    fi

    echo "----------------------------------------"

    if [[ $rc -ne 0 && $rc_err -ne 0 ]]; then
        sleep 5
    fi
done

if [ -e $OUT_DIR/results.json ] && [ -x $REAL_DIR/bulk-result.py ]; then
    cd $OUT_DIR
    $REAL_DIR/bulk-result.py results.json
    cd ..
fi

TIME_END_BULK=$(date +%s)
TIME_TOTAL_BULK=$(expr $TIME_END_BULK - $TIME_START_BULK)

echo ""

echo "AWS IoT bulk provisioning results"
echo "--------------------------------------------------------------"
echo "THING_BASENAME: $THING_BASENAME"
echo "NUM_THINGS: $NUM_THINGS"
echo "START: $(date -d@$TIME_START_BULK +'%Y-%m-%d %H:%M:%S')"
echo "END: $(date -d@$TIME_END_BULK +'%Y-%m-%d %H:%M:%S')"
echo "time to generate keys and CSRs: $TIME_TOTAL_GEN_KEYS secs."
echo "time for bulk provisioning: $TIME_TOTAL_BULK secs."
