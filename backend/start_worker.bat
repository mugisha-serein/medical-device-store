@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
env\Scripts\celery -A app.notifications.tasks worker --loglevel=info --concurrency=2
