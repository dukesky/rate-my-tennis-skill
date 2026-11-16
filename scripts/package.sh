#!/usr/bin/env bash
# Build distributable packages into dist/
#   dist/rate-my-tennis.zip        -> upload as a Skill (Claude apps) or unzip into a skills folder
#   dist/chatgpt-knowledge/        -> flat files to upload as Knowledge of a Custom GPT / Project
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf dist && mkdir -p dist/chatgpt-knowledge
(cd skill && zip -qr ../dist/rate-my-tennis.zip rate-my-tennis -x '*/__pycache__/*' '*.pyc' '*.DS_Store')
cp skill/rate-my-tennis/SKILL.md skill/rate-my-tennis/scripts/*.py skill/rate-my-tennis/references/*.md \
   skill/rate-my-tennis/assets/pose_landmarker_full.task dist/chatgpt-knowledge/
cp chatgpt/instructions.md dist/chatgpt-instructions.md
ls -lh dist dist/chatgpt-knowledge
