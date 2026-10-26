#!/bin/sh
# Every start: DemoStore's systems. The first start downloads the images and creates Ledgerline's schema and test data
# (a few minutes); later starts take seconds. python doctor.py tells you when everything answers.
cd "$(dirname "$0")/.."
docker compose -f sandbox/systems/compose.yaml up -d
