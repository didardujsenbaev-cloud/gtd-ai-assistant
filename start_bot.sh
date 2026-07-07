#!/bin/bash
cd /Users/dida/Desktop/gtd-ai-assistant
source venv/bin/activate
python3 telegram_bot.py >> bot.log 2>&1
