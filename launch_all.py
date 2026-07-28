#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键预处理并运行 2026H1 OMS、DMS 三单匹配。"""

import argparse
from pathlib import Path
import subprocess
import sys


def run(script: Path, *args: str) -> None:
    print(f'\n运行 {script.name} ...')
    subprocess.run([sys.executable, str(script), *args], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rebuild', action='store_true', help='强制重新生成三份 PKL')
    parser.add_argument('--preprocess-only', action='store_true', help='仅执行预处理')
    args = parser.parse_args()
    code_dir = Path(__file__).resolve().parent

    preprocess_args = ('--force',) if args.rebuild else ()
    run(code_dir / 'preprocess_2026.py', *preprocess_args)
    if args.preprocess_only:
        return
    run(code_dir / 'match_oms.py')
    run(code_dir / 'match_dms.py')
    print('\n2026年1-6月 OMS、DMS 三单匹配全部完成。')


if __name__ == '__main__':
    main()

