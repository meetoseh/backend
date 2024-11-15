#!/usr/bin/env bash
main() {
    . venv/bin/activate
    . /home/ec2-user/config.sh
    export AWS_METADATA_SERVICE_NUM_ATTEMPTS=5
    uvicorn main:app --port 80 --host 0.0.0.0
}

main
