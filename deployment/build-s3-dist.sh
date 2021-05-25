#!/bin/bash

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
#
# This assumes all of the OS-level configuration has been completed and git repo has already been cloned
#
# This script should be run from the repo's deployment directory
# cd deployment
# ./build-s3-dist.sh source-bucket-base-name solution-name version-code
#
# Paramenters:
#  - source-bucket-base-name: Name for the S3 bucket location where the template will source the Lambda
#    code from. The template will append '-[region_name]' to this bucket name.
#    For example: ./build-s3-dist.sh solutions v1.0.0
#    The template will then expect the source code to be located in the solutions-[region_name] bucket
#
#  - solution-name: name of the solution for consistency
#
#  - version-code: version of the package

set -e

# Check to see if input has been provided:
if [ -z "$1" ] || [ -z "$2" ] || [ -z "$3" ]; then
    echo "Please provide the base source bucket name, trademark approved solution name and version where the lambda code will eventually reside."
    echo "For example: ./build-s3-dist.sh solutions trademarked-solution-name v1.0.0"
    exit 1
fi

DIST_OUTPUT_BUCKET=$1
SOLUTION_NAME=$2
VERSION=$3

echo "DIST_OUTPUT_BUCKET: $DIST_OUTPUT_BUCKET SOLUTION_NAME: $SOLUTION_NAME VERSION: $VERSION"

echo ./build-s3-dist.sh $1 $2 $3

# Get reference for all important folders
deployment_dir="$PWD"
template_dist_dir="$deployment_dir/global-s3-assets"
build_dist_dir="$deployment_dir/regional-s3-assets"
source_dir="$deployment_dir/../source"
template_dir="$deployment_dir/../source/cfn"
opensource_dir="$deployment_dir/open-source"
opensource_template_dir="$opensource_dir/deployment"

echo "deployment_dir: $deployment_dir"

echo "------------------------------------------------------------------------------"
echo "[Init] Clean old dist, node_modules and bower_components folders"
echo "------------------------------------------------------------------------------"
echo "rm -rf $template_dist_dir"
rm -rf $template_dist_dir
echo "mkdir -p $template_dist_dir"
mkdir -p $template_dist_dir
echo "rm -rf $build_dist_dir"
rm -rf $build_dist_dir
echo "mkdir -p $build_dist_dir"
mkdir -p $build_dist_dir

echo "rm -rf $opensource_dir"
rm -rf $opensource_dir
echo "mkdir -p $opensource_dir"
mkdir -p $opensource_dir
echo "mkdir -p $opensource_template_dir"
mkdir -p $opensource_template_dir

echo "------------------------------------------------------------------------------"
echo "[Packing] Templates"
echo "------------------------------------------------------------------------------"

#cd ../source/cfn
for type in json template yaml; do
  count=$(ls -l *.$type 2>/dev/null|wc -l)
  echo "cp type: $type count: $count"
  if [ $count != 0 ]; then
    echo cp *.$type $template_dist_dir/
    cp *.$type $template_dist_dir/
  fi
done

cd $template_dist_dir

# Rename all *.json and *.yaml to *.template
for type in json yaml; do
  count=$(ls -l *.$type 2>/dev/null|wc -l)
  echo "rename type: $type count: $count"
  if [ $count != 0 ]; then
    for f in *.$type; do
      echo mv -- "$f" "${f%.$type}.template"
      mv -- "$f" "${f%.$type}.template"
    done
  fi
done
pwd
ls -l

echo "------------------------------------------------------------------------------"
echo "[Build] preparing CloudFormation templates"
echo "------------------------------------------------------------------------------"

for template in $(find . -name "*.template"); do
  echo "  template=$template"
  sed -i -e "s/__S3_BUCKET__/${DIST_OUTPUT_BUCKET}/g" \
      -e "s/__SOLUTION_NAME__/${SOLUTION_NAME}/g" \
      -e "s/__VERSION__/${VERSION}/g" $template
done

echo "------------------------------------------------------------------------------"
echo "[Build] copying source dir to open-source dir"
echo "------------------------------------------------------------------------------"
echo "cp -r $source_dir $opensource_dir"
cp -r $source_dir $opensource_dir
echo "------------------------------------------------------------------------------"
echo "opensource_dir: $opensource_dir/"
echo "------------------------------------------------------------------------------"
find $opensource_dir/

echo "------------------------------------------------------------------------------"
echo "[Build] cleaning Jupyter notebooks"
echo "------------------------------------------------------------------------------"

cd $source_dir

cd jupyter
# 01_IoTDR_Shared.ipynb
sed -r -i -e "s/config\['aws_region_pca'\] = .*$/config\['aws_region_pca'\] = \\\\\"REPLACE_WITH_AWS_REGION_FOR_PCA\\\\\"\\\n\",/g" \
    -e "s/config\['aws_region_primary'\] = .*$/config\['aws_region_primary'\] = \\\\\"REPLACE_WITH_AWS_PRIMARY_REGION\\\\\"\\\n\",/g" \
    -e "s/config\['aws_region_secondary'\] = .*$/config\['aws_region_secondary'\] = \\\\\"REPLACE_WITH_AWS_SECONDARY_REGION\\\\\"\\\n\",/g" \
    -e "s/config\['Sub_CN'\] = .*$/config\['Sub_CN'\] = \\\\\"REPLACE_WITH_YOUR_PCA_CN\\\\\"\\\n\",/g" \
    01_IoTDR_Shared.ipynb

# 04_IoTDR_Device_Certs.ipynb
sed -r -i -e "s/thing_name = .*$/thing_name = 'REPLACE_WITH_THING_NAME_OF_YOUR_CHOICE'\\\n\",/g" \
   04_IoTDR_Device_Certs.ipynb

# 05_IoTDR_JITR_Device.ipynb
sed -r -i -e "s/thing_name = .*$/thing_name = 'REPLACE_WITH_THING_NAME_OF_YOUR_CHOICE'\\\n\",/g" \
   05_IoTDR_JITR_Device.ipynb
cd ..

echo "------------------------------------------------------------------------------"
echo "[Build] zip packages"
echo "------------------------------------------------------------------------------"

echo "creating iot-dr-solution.zip"
rm -f iot-dr-solution.zip
ls -al

zip -q iot-dr-solution.zip -r cfn jupyter tools lambda launch-solution-code-build.sh launch-solution.yml
echo "cp iot-dr-solution.zip $build_dist_dir/"
cp iot-dr-solution.zip $build_dist_dir/

echo "creating installation packages for lambda"
pip3 --version
cd lambda

echo "installing pyOpenSSL for iot-mr-jitr"
echo pip3 install pyOpenSSL -t iot-mr-jitr -q
pip3 install pyOpenSSL -t iot-mr-jitr -q

for lambda in iot-dr-launch-solution iot-mr-jitr iot-mr-cross-region \
  sfn-iot-mr-dynamo-trigger  sfn-iot-mr-thing-crud \
  sfn-iot-mr-thing-group-crud sfn-iot-mr-thing-type-crud \
  sfn-iot-mr-shadow-syncer \
  iot-dr-missing-device-replication \
  iot-dr-create-r53-checker
do
  echo "creating lambda zip package for \"$lambda\""
  rm -f ${lambda}.zip
  cd $lambda
  zip -q ../${lambda}.zip -r .
  cd ..
done

# layer
cd iot-dr-layer
rm -rf python
mkdir python

echo pip3 install dynamodb-json==1.3 --no-deps -t python -q
pip3 install dynamodb-json==1.3 --no-deps -t python -q

echo pip3 install simplejson==3.17.2 -t python -q
pip3 install simplejson==3.17.2 -t python -q

cp device_replication.py python/

rm -f ../iot-dr-layer.zip
zip ../iot-dr-layer.zip -r python
cd ..

echo "ZIP files:"
ls -l *.zip
cp *.zip $build_dist_dir/



echo "------------------------------------------------------------------------------"
echo "global-s3-assets: $template_dist_dir/"
echo "------------------------------------------------------------------------------"
ls -al $template_dist_dir/
#echo cat $template_dist_dir/disaster-recovery-for-aws-iot.template
#cat $template_dist_dir/disaster-recovery-for-aws-iot.template

echo "------------------------------------------------------------------------------"
echo "regional-s3-assets: $build_dist_dir"
echo "------------------------------------------------------------------------------"
ls -al $build_dist_dir/
exit 0
