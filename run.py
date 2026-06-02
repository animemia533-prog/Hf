#!/usr/bin/env python3
"""
Entry point — loads .env then runs the bot.
Run: python run.py
"""
from dotenv import load_dotenv
load_dotenv()

from bot import main
main()
