#!/usr/bin/env python3
"""
华为云 DWS SQL 预处理器

在 sqlglot 解析之前预处理 DWS 特有语法，避免解析警告。

VERSION: 1.0.0
"""

import re
import typing as t


class DWSSQLPreprocessor:
    """DWS SQL 预处理器 - 移除 DWS 特有语法以便 sqlglot 解析"""
    
    DISTRIBUTE_BY_PATTERN = re.compile(
        r'\bDISTRIBUTE\s+BY\s+(?:HASH\s*\([^)]+\)|REPLICATION|ROUNDROBIN)',
        re.IGNORECASE | re.DOTALL
    )
    
    WITH_OPTIONS_PATTERN = re.compile(
        r'\bWITH\s*\(\s*'
        r'(?:ORIENTATION\s*=\s*(?:COLUMN|ROW)\s*,?\s*)?'
        r'(?:COMPRESSION\s*=\s*(?:LOW|MIDDLE|HIGH)\s*,?\s*)?'
        r'(?:\w+\s*=\s*\w+\s*,?\s*)*'
        r'\)',
        re.IGNORECASE
    )
    
    def preprocess(self, sql: str) -> t.Tuple[str, dict]:
        """预处理 DWS SQL，移除特有语法
        
        Returns:
            (clean_sql, removed_info)
        """
        removed = {
            "distribute_by": [],
            "with_options": [],
        }
        
        for match in self.DISTRIBUTE_BY_PATTERN.finditer(sql):
            removed["distribute_by"].append(match.group(0).strip())
        
        for match in self.WITH_OPTIONS_PATTERN.finditer(sql):
            removed["with_options"].append(match.group(0).strip())
        
        clean_sql = self.DISTRIBUTE_BY_PATTERN.sub('', sql)
        clean_sql = self.WITH_OPTIONS_PATTERN.sub('', clean_sql)
        clean_sql = re.sub(r'\n\s*\n\s*\n', '\n\n', clean_sql)
        
        return clean_sql.strip(), removed
    
    def validate_dws_syntax(self, sql: str) -> dict:
        """验证 DWS 特有语法"""
        results = {
            "valid": True,
            "errors": [],
            "warnings": [],
            "distribute_by": None,
            "orientation": None,
            "compression": None,
        }
        
        distribute_matches = list(self.DISTRIBUTE_BY_PATTERN.finditer(sql))
        if distribute_matches:
            clause = distribute_matches[-1].group(0).upper()
            results["distribute_by"] = clause
            
            if "HASH" in clause:
                hash_match = re.search(r'HASH\s*\(([^)]+)\)', clause)
                if hash_match:
                    columns = [c.strip() for c in hash_match.group(1).split(',')]
                    if not all(columns):
                        results["errors"].append("DISTRIBUTE BY HASH 缺少列名")
                        results["valid"] = False
        
        with_match = self.WITH_OPTIONS_PATTERN.search(sql)
        if with_match:
            with_clause = with_match.group(0).upper()
            
            orient_match = re.search(r'ORIENTATION\s*=\s*(COLUMN|ROW)', with_clause)
            if orient_match:
                results["orientation"] = orient_match.group(1)
            
            compress_match = re.search(r'COMPRESSION\s*=\s*(LOW|MIDDLE|HIGH)', with_clause)
            if compress_match:
                results["compression"] = compress_match.group(1)
        
        return results


def preprocess_dws_sql(sql: str) -> t.Tuple[str, dict]:
    """便捷函数：预处理 DWS SQL"""
    preprocessor = DWSSQLPreprocessor()
    return preprocessor.preprocess(sql)


def validate_dws_syntax(sql: str) -> dict:
    """便捷函数：验证 DWS 语法"""
    preprocessor = DWSSQLPreprocessor()
    return preprocessor.validate_dws_syntax(sql)


if __name__ == "__main__":
    test_sql = """
    CREATE TABLE slprd.dwb_product_center_f (
        product_id BIGINT,
        product_name VARCHAR(200)
    ) 
    WITH (
        ORIENTATION = COLUMN,
        COMPRESSION = LOW
    )
    DISTRIBUTE BY HASH(product_id);
    """
    
    preprocessor = DWSSQLPreprocessor()
    clean_sql, removed = preprocessor.preprocess(test_sql)
    
    print("原始 SQL:")
    print(test_sql)
    print("\n清理后 SQL:")
    print(clean_sql)
    print("\n移除内容:")
    print(f"  DISTRIBUTE BY: {removed['distribute_by']}")
    print(f"  WITH 选项: {removed['with_options']}")
    
    validation = preprocessor.validate_dws_syntax(test_sql)
    print(f"\n验证结果: {'✅ 通过' if validation['valid'] else '❌ 失败'}")
    print(f"DISTRIBUTE BY: {validation['distribute_by']}")
    print(f"ORIENTATION: {validation['orientation']}")
    print(f"COMPRESSION: {validation['compression']}")
