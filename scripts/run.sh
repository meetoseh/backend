#!/usr/bin/env bash
main() {
    . venv/bin/activate
    . /home/ec2-user/config.sh
    uvicorn main:app --port 80 --host 0.0.0.0
}

main
