#!/usr/bin/env python3

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0.

import json
import os
import sys


def process_line(line):
    d = json.loads(line)
    crt = d["response"]["CertificatePem"]
    thing = d["response"]["ResourceArns"]["thing"].split('/')[1]
    print("creating file {}.crt for thing {}".format(thing, thing))
    file = open(thing + ".crt", "w")
    file.write(crt)
    file.close()

def process_results(file):
    try:
        with open(file) as f:
            for line in f:
                process_line(line)
        f.close()
    except Exception as e:
        print("error opening file {}: {}".format(file,e))
        return None

def main(argv):
    if len(argv) == 0:
        print("usage: {} <result_filename>".format(os.path.basename(__file__)))
        sys.exit(1)

    process_results(argv[0])

if __name__ == "__main__":
    main(sys.argv[1:])
