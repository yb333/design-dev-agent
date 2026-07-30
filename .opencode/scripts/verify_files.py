#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DWS ETL 管道文件完整性验证脚本
版本: v2.0.0 (跨平台版本)
创建时间: 2026-03-01
用途: 验证编码阶段生成的DDL/ETL文件是否完整
支持: Windows, macOS, Linux
"""

import os
import re
import sys
import argparse
from pathlib import Path
from typing import List, Tuple, Optional


class Colors:
    if sys.platform == 'win32':
        RED = ''
        GREEN = ''
        YELLOW = ''
        NC = ''
    else:
        RED = '\033[0;31m'
        GREEN = '\033[0;32m'
        YELLOW = '\033[1;33m'
        NC = '\033[0m'


def print_error(msg: str):
    print(f"{Colors.RED}错误: {msg}{Colors.NC}")


def print_success(msg: str):
    print(f"{Colors.GREEN}✓{Colors.NC} {msg}")


def print_warning(msg: str):
    print(f"{Colors.YELLOW}!{Colors.NC} {msg}")


def print_fail(msg: str):
    print(f"{Colors.RED}✗{Colors.NC} {msg}")


def extract_file_number(filename: str) -> Optional[str]:
    match = re.match(r'^(\d+)_', filename)
    return match.group(1) if match else None


def count_lines(filepath: Path) -> int:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return sum(1 for _ in f)
    except:
        return 0


def verify_files(target_dir: str, design_doc: Optional[str] = None) -> bool:
    target_path = Path(target_dir)
    
    if not target_path.exists():
        print_error(f"目标目录不存在: {target_dir}")
        return False
    
    ddl_dir = target_path / "04_ddl"
    etl_dir = target_path / "05_etl"
    
    if not ddl_dir.exists():
        print_error(f"DDL目录不存在: {ddl_dir}")
        return False
    
    if not etl_dir.exists():
        print_error(f"ETL目录不存在: {etl_dir}")
        return False
    
    print("=" * 42)
    print("DWS ETL 管道文件完整性验证")
    print("=" * 42)
    print()
    print(f"目标目录: {target_dir}")
    print(f"DDL目录: {ddl_dir}")
    print(f"ETL目录: {etl_dir}")
    print()
    
    ddl_files = sorted(ddl_dir.glob("*.sql"))
    etl_files = sorted(etl_dir.glob("*.sql"))
    
    ddl_count = len(ddl_files)
    etl_count = len(etl_files)
    
    print(f"{Colors.YELLOW}=== 检查 DDL 文件 ==={Colors.NC}")
    print()
    print(f"DDL 文件数量: {ddl_count}")
    print()
    
    if ddl_count == 0:
        print_error("未找到任何 DDL 文件")
        return False
    
    print("DDL 文件列表:")
    for f in ddl_files:
        lines = count_lines(f)
        print_success(f"{f.name} ({lines} 行)")
    print()
    
    print(f"{Colors.YELLOW}=== 检查 ETL 文件 ==={Colors.NC}")
    print()
    print(f"ETL 文件数量: {etl_count}")
    print()
    
    if etl_count == 0:
        print_error("未找到任何 ETL 文件")
        return False
    
    print("ETL 文件列表:")
    for f in etl_files:
        lines = count_lines(f)
        print_success(f"{f.name} ({lines} 行)")
    print()
    
    print(f"{Colors.YELLOW}=== DDL-ETL 一致性检查 ==={Colors.NC}")
    print()
    
    ddl_nums = set()
    ddl_num_to_name = {}
    for f in ddl_files:
        num = extract_file_number(f.name)
        if num:
            ddl_nums.add(num)
            ddl_num_to_name[num] = f.name
    
    etl_nums = set()
    etl_num_to_name = {}
    for f in etl_files:
        num = extract_file_number(f.name)
        if num:
            etl_nums.add(num)
            etl_num_to_name[num] = f.name
    
    missing_etl = []
    for num in sorted(ddl_nums):
        if num not in etl_nums:
            ddl_name = ddl_num_to_name.get(num, "unknown")
            missing_etl.append(f"{num}_insert_xxx.sql (对应 DDL: {ddl_name})")
    
    orphan_etl = []
    for num in sorted(etl_nums):
        if num not in ddl_nums:
            etl_name = etl_num_to_name.get(num, "unknown")
            orphan_etl.append(f"{etl_name} (无对应 DDL)")
    
    if missing_etl:
        print(f"{Colors.RED}缺失的 ETL 文件:{Colors.NC}")
        for f in missing_etl:
            print_fail(f)
        print()
    
    if orphan_etl:
        print(f"{Colors.YELLOW}孤立的 ETL 文件（无对应 DDL）:{Colors.NC}")
        for f in orphan_etl:
            print_warning(f)
        print()
    
    print(f"{Colors.YELLOW}=== 强制检查点验证 ==={Colors.NC}")
    print()
    
    confirm_dir = target_path / "03_confirm"
    if confirm_dir.exists():
        print_success("03_confirm 目录存在")
        readme = confirm_dir / "README.md"
        confirmation = confirm_dir / "confirmation.md"
        if readme.exists() or confirmation.exists():
            print_success("确认记录文件存在")
        else:
            print_warning("03_confirm 目录存在但缺少确认记录文件")
    else:
        print_fail("03_confirm 目录缺失 - 违反强制执行规范！")
        print_error("必须在用户确认后创建 03_confirm 目录")
    print()
    
    print("=" * 42)
    print("验证摘要")
    print("=" * 42)
    print()
    print(f"DDL 文件: {ddl_count}")
    print(f"ETL 文件: {etl_count}")
    print(f"缺失 ETL: {len(missing_etl)}")
    print(f"孤立 ETL: {len(orphan_etl)}")
    print()
    
    if missing_etl or orphan_etl:
        print(f"{Colors.RED}验证结果: ✗ 不通过{Colors.NC}")
        print()
        print("建议操作:")
        if missing_etl:
            print("  1. 补充生成缺失的 ETL 文件")
        if orphan_etl:
            print("  2. 检查孤立的 ETL 文件是否需要删除或补充 DDL")
        return False
    else:
        print(f"{Colors.GREEN}验证结果: ✓ 通过{Colors.NC}")
        return True


def main():
    parser = argparse.ArgumentParser(
        description='DWS ETL 管道文件完整性验证脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
示例:
  python verify_files.py docs/output/用户中心宽表
  python verify_files.py docs/output/订单中心宽表 --design-doc docs/output/订单中心宽表/02_design/design.md
        '''
    )
    parser.add_argument('target_dir', help='包含 01_input, 02_design, 04_ddl, 05_etl 等子目录的根目录')
    parser.add_argument('--design-doc', help='设计文档路径（可选，用于提取预期文件列表）')
    
    args = parser.parse_args()
    
    success = verify_files(args.target_dir, args.design_doc)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
