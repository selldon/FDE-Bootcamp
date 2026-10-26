#!/bin/sh
# Once, when the environment is created: the Python packages of the product and of the labs, the widget's packages,
# Claude Code, and the two settings files from their examples (without a key: Codespaces passes it as a secret).
set -e
cd "$(dirname "$0")/.."
pip install --no-cache-dir -r requirements.txt -r sandbox/requirements.txt
(cd widget && npm ci)
npm install -g @anthropic-ai/claude-code
[ -f .env ] || cp .env.example .env
[ -f sandbox/.env ] || cp sandbox/.env.example sandbox/.env
pre-commit install
echo "Ready. Next: python doctor.py"
