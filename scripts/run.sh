#!/usr/bin/env bash
main() {
    . venv/bin/activate
    . /home/ec2-user/config.sh
    uvicorn main:app --workers 16 --port 80 --host 0.0.0.0
}

main
