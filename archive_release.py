#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成轻量、可校验的2026H1项目归档。

归档复制生产代码和关键文档，但不复制原始输入、PKL或正式结果大文件；
后者通过项目文件清单的相对路径、大小、修改时间和SHA256固定版本。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
from datetime import datetime
from pathlib import Path


CODE_DIR = Path(__file__).resolve().parent
BASE_DIR = CODE_DIR.parent
ARCHIVE_ROOT = BASE_DIR / 'archive' / '2026H1'


def sha256(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    """流式计算文件SHA256，避免读取大文件时占用过多内存。"""
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def is_business_file(path: Path) -> bool:
    """排除系统缓存、Office临时文件和Python字节码。"""
    name = path.name
    return (
        path.is_file()
        and name != '.DS_Store'
        and not name.startswith('~$')
        and not name.startswith('.~')
        and not any(part.startswith('_') for part in path.parts)
        and '__pycache__' not in path.parts
        and path.suffix != '.pyc'
    )


def copy_release_files(release_dir: Path) -> None:
    """复制生产代码及关键文档，不复制原始数据和正式结果。"""
    code_target = release_dir / 'code 2026'
    code_target.mkdir(parents=True, exist_ok=True)
    for source in sorted(CODE_DIR.iterdir()):
        if is_business_file(source) and source.suffix in {'.py', '.md', '.txt'}:
            shutil.copy2(source, code_target / source.name)

    docs_target = release_dir / '文档'
    docs_target.mkdir(parents=True, exist_ok=True)
    document_sources = [
        BASE_DIR / 'README.md',
        BASE_DIR / '项目进度_2026H1.md',
        BASE_DIR / '2026H1销售三单匹配口径说明.txt',
        BASE_DIR / 'AQPP 三单匹配场景规范_full.xlsx',
        BASE_DIR / '交付文档' / '2026H1销售三单匹配_Audit疑问回复_20260728.docx',
        BASE_DIR / 'archive' / 'README.md',
    ]
    for source in document_sources:
        if source.exists():
            shutil.copy2(source, docs_target / source.name)


def inventory_sources() -> list[tuple[str, Path]]:
    """列出需要锁定版本的当前生产文件；不包含历史代码和参考项目。"""
    roots = [
        ('生产代码', CODE_DIR),
        ('原始输入', BASE_DIR / 'input'),
        ('标准化PKL', BASE_DIR / 'pkl' / '2026H1'),
        ('正式输出', BASE_DIR / 'output' / '2026H1'),
        ('交付文档', BASE_DIR / '交付文档'),
    ]
    files: list[tuple[str, Path]] = []
    for category, root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob('*')):
            if is_business_file(path):
                files.append((category, path))
    for path in (
        BASE_DIR / 'README.md',
        BASE_DIR / '项目进度_2026H1.md',
        BASE_DIR / '2026H1销售三单匹配口径说明.txt',
        BASE_DIR / 'AQPP 三单匹配场景规范_full.xlsx',
    ):
        if path.exists():
            files.append(('项目根文档', path))
    return files


def write_csv(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    """以Excel兼容UTF-8编码写出清单。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def write_project_inventory(path: Path) -> None:
    """记录生产文件元数据及SHA256，锁定未复制大文件的版本。"""
    rows = []
    for category, source in inventory_sources():
        stat = source.stat()
        rows.append([
            category,
            str(source.relative_to(BASE_DIR)),
            stat.st_size,
            round(stat.st_size / 1024 / 1024, 3),
            datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec='seconds'),
            sha256(source),
        ])
    write_csv(
        path,
        ['类别', '项目相对路径', '字节数', 'MB', '最后修改时间', 'SHA256'],
        rows,
    )


def write_archive_manifest(release_dir: Path) -> None:
    """记录归档内文件；清单自身和校验文件由SHA256SUMS继续覆盖。"""
    manifest_path = release_dir / '清单' / '归档文件清单.csv'
    rows = []
    for path in sorted(release_dir.rglob('*')):
        if not is_business_file(path) or path == manifest_path or path.name == 'SHA256SUMS.txt':
            continue
        stat = path.stat()
        rows.append([
            str(path.relative_to(release_dir)),
            stat.st_size,
            round(stat.st_size / 1024 / 1024, 3),
            sha256(path),
        ])
    write_csv(manifest_path, ['归档相对路径', '字节数', 'MB', 'SHA256'], rows)


def write_checksums(release_dir: Path) -> None:
    """为归档中除校验文件自身外的所有文件生成SHA256SUMS。"""
    checksum_path = release_dir / '清单' / 'SHA256SUMS.txt'
    lines = []
    for path in sorted(release_dir.rglob('*')):
        if is_business_file(path) and path != checksum_path:
            lines.append(f'{sha256(path)}  {path.relative_to(release_dir)}')
    checksum_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def write_release_readme(release_dir: Path, version: str) -> None:
    """生成版本专属归档说明。"""
    text = f"""# {version}归档

生成日期：{datetime.now().astimezone().isoformat(timespec='seconds')}

本目录是2026H1销售toB三单匹配项目的轻量冻结版本，包含生产代码、测试、项目进度、
AQPP规范、管理层口径说明和Audit回复。

原始输入、标准化PKL和正式结果未重复复制。请使用`清单/项目文件清单.csv`中的
项目相对路径、文件大小、最后修改时间和SHA256确认对应大文件；
使用`清单/SHA256SUMS.txt`核验本归档目录内文件。

生产执行入口：`code 2026/launch_all.py`。
业务口径入口：`code 2026/README.md`。
当前进度入口：`文档/项目进度_2026H1.md`。
"""
    (release_dir / 'README.md').write_text(text, encoding='utf-8')


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='生成版本化轻量归档和校验清单')
    parser.add_argument('--version', default='2026H1_20260729_v2', help='归档版本目录及ZIP名称')
    parser.add_argument('--replace', action='store_true', help='仅在明确需要时覆盖同名归档')
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    release_dir = ARCHIVE_ROOT / args.version
    zip_path = ARCHIVE_ROOT / f'{args.version}.zip'
    if release_dir.exists() or zip_path.exists():
        if not args.replace:
            raise FileExistsError(f'归档版本已存在：{args.version}；如需重建请显式使用--replace')
        if release_dir.exists():
            shutil.rmtree(release_dir)
        if zip_path.exists():
            zip_path.unlink()

    release_dir.mkdir(parents=True, exist_ok=False)
    copy_release_files(release_dir)
    write_release_readme(release_dir, args.version)
    write_project_inventory(release_dir / '清单' / '项目文件清单.csv')
    write_archive_manifest(release_dir)
    write_checksums(release_dir)
    shutil.make_archive(str(zip_path.with_suffix('')), 'zip', root_dir=release_dir)
    print(f'归档目录：{release_dir}')
    print(f'归档压缩包：{zip_path}')


if __name__ == '__main__':
    main()
