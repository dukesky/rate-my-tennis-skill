#!/usr/bin/env bash
# Build distributable packages into dist/
#   dist/rate-my-tennis.zip                -> upload as a Skill (Claude apps) or unzip into a skills folder
#   dist/rate-my-tennis-chatgpt.zip        -> unzip; upload the files as Knowledge of a Custom GPT / Project
#   dist/chatgpt-knowledge/                -> the same files, unzipped
set -euo pipefail
cd "$(dirname "$0")/.."
SKILL=plugins/rate-my-tennis/skills/rate-my-tennis
rm -rf dist && mkdir -p dist/chatgpt-knowledge
(cd "$(dirname "$SKILL")" && zip -qr "$OLDPWD/dist/rate-my-tennis.zip" rate-my-tennis -x '*/__pycache__/*' '*.pyc' '*.DS_Store')
cp "$SKILL"/SKILL.md "$SKILL"/scripts/*.py "$SKILL"/references/*.md "$SKILL"/assets/pose_landmarker_full.task dist/chatgpt-knowledge/
cp chatgpt/instructions.md dist/chatgpt-knowledge/INSTRUCTIONS-paste-into-GPT.md
(cd dist && zip -qr rate-my-tennis-chatgpt.zip chatgpt-knowledge)
ls -lh dist
