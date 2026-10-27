#!/usr/bin/env python3
"""Rhythm Crafter Player —— 启动入口。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from wavemusic.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
