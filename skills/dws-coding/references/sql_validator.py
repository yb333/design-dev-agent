#!/usr/bin/env python3
"""
DWS ETL SQL 语法检查工具

功能:
1. 括号平衡检查
2. 引号平衡检查  
3. SQL 关键字拼写检查
4. INSERT 字段数量匹配检查
5. DDL-ETL 字段一致性检查

使用方法:
    python sql_validator.py --ddl-dir ./ddl --etl-dir ./etl --output test_report.md
"""

import os
import sys
import re
import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

VERSION = "2.5.0"
CHANGELOG = """
v2.5.0 (2026-04-11):
  - 新增: DDL 禁止 DROP TABLE 检查
  - 新增: DDL 必须 CREATE IF NOT EXISTS 检查
  - 新增: DDL TO GROUP 逻辑集群检查
v2.4.0 (2026-04-09):
  - 新增: DDL 内联 COMMENT 检查，检测 MySQL 风格的 col TYPE COMMENT 'xxx' 语法
v2.3.0 (2026-03-10):
  - 新增: 单文件模式支持 (--file, --type 参数)
  - 新增: validate_single_file() 方法
  - 优化: 支持每个脚本生成后立即验证
v2.2.3 (2026-02-28):
  - 优化: 添加 Windows 控制台 UTF-8 编码支持
v2.2.2 (2026-02-28):
  - 修复: _count_select_fields() 正确处理 CASE WHEN 内部逗号
  - 影响: 解决大型 ETL 字段计数误报问题
  - 改进: 使用更清晰的变量名和简化逻辑
v2.2.1 (2026-02-25):
  - 修复: _parse_ddl() 字段类型匹配增加 NVARCHAR2/VARCHAR2/NUMBER 等类型
v2.0.0 (2026-02-18):
  - 重大改进: 使用sqlglot AST解析准确识别别名
v1.0.0:
  - 初始版本
"""

# 尝试导入 sqlglot，用于 AST 解析
try:
    import sqlglot
    from sqlglot import exp
    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False
    print("警告: 未安装 sqlglot，将使用基础别名识别。建议执行: pip install sqlglot")

# 导入 DWS 预处理器
try:
    from pathlib import Path
    _dws_preprocessor_path = Path(__file__).parent / "dws_preprocessor.py"
    if _dws_preprocessor_path.exists():
        import importlib.util
        _spec = importlib.util.spec_from_file_location("dws_preprocessor", _dws_preprocessor_path)
        _dws_module = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(_dws_module)
        DWSSQLPreprocessor = _dws_module.DWSSQLPreprocessor
        preprocess_dws_sql = _dws_module.preprocess_dws_sql
        validate_dws_syntax = _dws_module.validate_dws_syntax
        HAS_DWS_PREPROCESSOR = True
    else:
        HAS_DWS_PREPROCESSOR = False
        DWSSQLPreprocessor = None
        preprocess_dws_sql = None
        validate_dws_syntax = None
except Exception:
    HAS_DWS_PREPROCESSOR = False
    DWSSQLPreprocessor = None
    preprocess_dws_sql = None
    validate_dws_syntax = None


class SQLValidator:
    """SQL 语法验证器"""
    
    # DWS 支持的 SQL 关键字
    SQL_KEYWORDS = {
        # 基本 SQL 语句
        'SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'FULL',
        'CROSS', 'NATURAL', 'SELF',
        'ON', 'AND', 'OR', 'NOT', 'IN', 'EXISTS', 'BETWEEN', 'LIKE', 'IS', 'NULL',
        'AS', 'DISTINCT', 'GROUP', 'BY', 'HAVING', 'ORDER', 'ASC', 'DESC', 'LIMIT',
        'OFFSET', 'FETCH', 'FIRST', 'NEXT', 'ROWS', 'ONLY',
        'INSERT', 'INTO', 'VALUES', 'UPDATE', 'SET', 'DELETE', 'CREATE', 'ALTER',
        'DROP', 'TABLE', 'INDEX', 'VIEW', 'SCHEMA', 'DATABASE', 'TRUNCATE',
        'PRIMARY', 'KEY', 'FOREIGN', 'REFERENCES', 'UNIQUE', 'CONSTRAINT',
        'CHECK', 'DEFAULT', 'IDENTITY', 'AUTO_INCREMENT',
        'WITH', 'RECURSIVE', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'IF',
        'WHILE', 'FOR', 'LOOP', 'BEGIN', 'COMMIT', 'ROLLBACK', 'TRANSACTION',
        'UNION', 'ALL', 'INTERSECT', 'EXCEPT', 'MINUS',
        
        # 数据类型
        'BIGINT', 'INTEGER', 'INT', 'SMALLINT', 'TINYINT',
        'DECIMAL', 'NUMERIC', 'FLOAT', 'DOUBLE', 'REAL',
        'VARCHAR', 'CHAR', 'CHARACTER', 'TEXT', 'CLOB', 'BLOB', 'BYTEA',
        'BOOLEAN', 'BOOL', 'TRUE', 'FALSE',
        'DATE', 'TIME', 'TIMESTAMP', 'TIMESTAMPTZ', 'INTERVAL',
        'ARRAY', 'JSON', 'JSONB', 'XML', 'UUID',
        'SERIAL', 'BIGSERIAL', 'SMALLSERIAL',
        
        # 聚合函数
        'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'STDDEV', 'VARIANCE', 'STDDEV_SAMP',
        'STDDEV_POP', 'VAR_SAMP', 'VAR_POP',
        'MODE', 'PERCENTILE_CONT', 'PERCENTILE_DISC',  # 有序集聚合函数
        'LISTAGG', 'STRING_AGG', 'ARRAY_AGG', 'XMLAGG',
        'BIT_AND', 'BIT_OR', 'BOOL_AND', 'BOOL_OR',
        'EVERY', 'GROUPING', 'GROUPING_ID',
        
        # 窗口函数
        'ROW_NUMBER', 'RANK', 'DENSE_RANK', 'PERCENT_RANK', 'CUME_DIST',
        'NTILE', 'LEAD', 'LAG', 'FIRST_VALUE', 'LAST_VALUE', 'NTH_VALUE',
        'OVER', 'PARTITION', 'WITHIN', 'RESPECT', 'IGNORE',
        
        # 日期时间函数
        'CURRENT_DATE', 'CURRENT_TIME', 'CURRENT_TIMESTAMP', 'NOW', 'TODAY',
        'EXTRACT', 'TO_DATE', 'TO_CHAR', 'TO_TIMESTAMP', 'TO_NUMBER',
        'DATEDIFF', 'TIMESTAMPDIFF', 'DATE_DIFF', 'DATEADD', 'DATE_ADD',
        'DATE_SUB', 'DATE_FORMAT', 'STR_TO_DATE',
        'YEAR', 'MONTH', 'DAY', 'HOUR', 'MINUTE', 'SECOND',
        'QUARTER', 'WEEK', 'WEEKDAY', 'YEARDAY',
        'DAYOFWEEK', 'DAYOFMONTH', 'DAYOFYEAR',
        'CURDATE', 'CURTIME', 'SYSDATE', 'GETDATE',
        'AGE', 'DATE_TRUNC', 'DATE_PART',
        
        # 字符串函数
        'SUBSTRING', 'CONCAT', 'CONCAT_WS', 'TRIM', 'UPPER', 'LOWER', 'LENGTH',
        'REPLACE', 'REVERSE', 'REPEAT', 'SPACE',
        'LPAD', 'RPAD', 'INSTR', 'POSITION', 'LOCATE',
        'SUBSTR', 'LEFT', 'RIGHT', 'MID',
        'SPLIT_PART', 'REGEXP', 'REGEXP_LIKE', 'REGEXP_REPLACE', 'REGEXP_SUBSTR',
        'CHAR_LENGTH', 'CHARACTER_LENGTH', 'OCTET_LENGTH', 'BIT_LENGTH',
        'INITCAP', 'MD5', 'SHA1', 'SHA256', 'ENCODE', 'DECODE',
        
        # 数学函数
        'ABS', 'CEIL', 'CEILING', 'FLOOR', 'ROUND', 'TRUNC', 'TRUNCATE',
        'MOD', 'POWER', 'SQRT', 'CBRT', 'EXP', 'LN', 'LOG', 'LOG10', 'LOG2',
        'SIGN', 'PI', 'RANDOM', 'SETSEED',
        'SIN', 'COS', 'TAN', 'ASIN', 'ACOS', 'ATAN', 'ATAN2',
        'SINH', 'COSH', 'TANH',
        'DEGREES', 'RADIANS',
        'DIV', 'FACTORIAL', 'GCD', 'LCM',
        
        # 条件函数
        'COALESCE', 'NVL', 'NULLIF', 'IFNULL', 'DECODE',
        'CAST', 'CONVERT', '::', 'TYPEOF',
        'GREATEST', 'LEAST',
        
        # 其他函数
        'GENERATE_SERIES', 'GENERATE_SUBSCRIPTS',
        'ARRAY_TO_STRING', 'STRING_TO_ARRAY',
        'ROW', 'ROWS', 'COLUMN', 'COLUMNS',
        'FORMAT', 'QUOTE_IDENT', 'QUOTE_LITERAL', 'QUOTE_NULLABLE',
        
        # DWS 特有
        'DISTRIBUTE', 'HASH', 'REPLICATION', 'ORIENTATION', 'ROW',
        'COMPRESSION', 'LOW', 'MIDDLE', 'HIGH', 'PARTITION', 'RANGE', 'LIST',
        'ANALYZE', 'EXPLAIN', 'USING', 'COMMENT', 'GRANT', 'REVOKE',
        'DECLARE', 'CURSOR', 'CLOSE', 'RETURN', 'RETURNS',
        'FUNCTION', 'PROCEDURE', 'TRIGGER', 'EXECUTE', 'CALL',
        'MERGE', 'MATCHED', 'GENERATED', 'ALWAYS', 'STORED', 'VIRTUAL',
        'DEFERRABLE', 'INITIALLY', 'IMMEDIATE', 'DEFERRED',
        'CASCADE', 'RESTRICT', 'NO', 'ACTION', 'RESET',
        'TEMPORARY', 'TEMP', 'UNLOGGED', 'LOGGED',
        'SEQUENCE', 'NEXTVAL', 'CURRVAL', 'SETVAL',
        'TABLESPACE', 'TABLESPACES', 'OWNER', 'TO',
        'NONE', 'UNKNOWN', 'OTHERS', 'OVERWRITE', 'APPEND',
        'VACUUM', 'CLUSTER', 'REINDEX',
        
        # 控制流
        'CONTINUE', 'BREAK', 'EXIT', 'RETURN', 'RAISE', 'ASSERT',
        'EXCEPTION', 'ERROR', 'NOTICE', 'WARNING',
        
        # 其他
        'ANY', 'SOME', 'BOTH', 'LEADING', 'TRAILING',
        'KEEP', 'DENSE_RANK_FIRST', 'DENSE_RANK_LAST',
    }
    
    # 常见拼写错误映射
    COMMON_TYPOS = {
        'SELET': 'SELECT',
        'FORM': 'FROM',
        'WHER': 'WHERE',
        'INSTER': 'INSERT',
        'INSET': 'INSERT',
        'UPATE': 'UPDATE',
        'DELEET': 'DELETE',
        'CREAT': 'CREATE',
        'ALTR': 'ALTER',
        'DRP': 'DROP',
        'JOINT': 'JOIN',
        'GROP': 'GROUP',
        'GRUP': 'GROUP',
        'ODER': 'ORDER',
        'ORDR': 'ORDER',
        'DISINCT': 'DISTINCT',
        'DISTICT': 'DISTINCT',
        'HVAING': 'HAVING',
        'HAVNG': 'HAVING',
        'BETWEN': 'BETWEEN',
        'BETEEN': 'BETWEEN',
        'EXITS': 'EXISTS',
        'EXSITS': 'EXISTS',
        'DISTIRBUTE': 'DISTRIBUTE',
        'ORINETATION': 'ORIENTATION',
        'COMPRESION': 'COMPRESSION',
        'PARTITON': 'PARTITION',
        'CONSTAINT': 'CONSTRAINT',
        'CONSTRANT': 'CONSTRAINT',
        'PRIMRAY': 'PRIMARY',
        'PRIMERY': 'PRIMARY',
        'FOREING': 'FOREIGN',
        'FORIGN': 'FOREIGN',
        'REFFERENCES': 'REFERENCES',
        'REFERNCES': 'REFERENCES',
        'TIMESTMAP': 'TIMESTAMP',
        'TIMESTMP': 'TIMESTAMP',
        'VARCHR': 'VARCHAR',
        'VARCHRA': 'VARCHAR',
        'DECMIAL': 'DECIMAL',
        'DECIMEL': 'DECIMAL',
        'BOOLEN': 'BOOLEAN',
        'BOLEAN': 'BOOLEAN',
    }
    
    def __init__(self):
        self.results = {
            'passed': [],
            'failed': [],
            'warnings': []
        }
    
    def extract_aliases(self, sql: str) -> Dict[str, str]:
        """
        使用 AST 解析提取所有表别名、CTE别名、子查询别名 (v2.2.0)
        
        返回: {alias_upper: table_name} 映射
        
        改进:
        - v2.2.0: 使用 DWS 预处理器移除 DWS 特有语法，避免解析警告
        - v2.0.0: 使用 sqlglot AST 解析，准确识别所有别名
        - 避免 Levenshtein 距离检测导致的误报
        """
        aliases = {}
        
        # v2.2.0: 预处理 DWS 特有语法
        clean_sql = sql
        if HAS_DWS_PREPROCESSOR and preprocess_dws_sql:
            clean_sql, _ = preprocess_dws_sql(sql)
        
        if not HAS_SQLGLOT:
            return self._extract_aliases_regex(sql)
        
        try:
            # 解析预处理后的 SQL 为 AST
            ast = sqlglot.parse_one(clean_sql, dialect='postgres')
            
            # 方法1: 遍历所有 Table 节点获取表别名
            for table in ast.find_all(exp.Table):
                if table.alias:
                    alias_name = str(table.alias).strip('"').upper()
                    table_name = table.name.upper()
                    aliases[alias_name] = table_name
            
            # 方法2: 提取 CTE 别名 (WITH ... AS)
            if hasattr(ast, 'with') and ast.with_:
                for cte in ast.with_.expressions:
                    if hasattr(cte, 'alias'):
                        cte_name = str(cte.alias).strip('"').upper()
                        aliases[cte_name] = 'CTE'
            
            # 方法3: 遍历 Subquery 节点获取子查询别名
            for subquery in ast.find_all(exp.Subquery):
                if subquery.alias:
                    alias_name = str(subquery.alias).strip('"').upper()
                    aliases[alias_name] = 'SUBQUERY'
                    
        except Exception as e:
            # AST 解析失败，降级到正则
            return self._extract_aliases_regex(sql)
        
        return aliases
    
    def _extract_aliases_regex(self, sql: str) -> Dict[str, str]:
        """
        降级方案: 使用正则表达式提取别名 (无sqlglot时使用)
        """
        aliases = {}
        sql_upper = sql.upper()
        
        # 提取 CTE 别名: WITH alias AS
        cte_pattern = r'\bWITH\s+(\w+)\s+AS\s*\('
        for match in re.finditer(cte_pattern, sql_upper):
            aliases[match.group(1)] = 'CTE'
        
        # 处理多个CTE: , alias AS (
        cte_cont_pattern = r',\s*(\w+)\s+AS\s*\('
        for match in re.finditer(cte_cont_pattern, sql_upper):
            aliases[match.group(1)] = 'CTE'
        
        # 提取表别名: FROM/JOIN table_name alias
        from_pattern = r'\bFROM\s+(\w+(?:\.\w+)?)\s+(\w+)\s*(?:,|JOIN|LEFT|RIGHT|INNER|WHERE|GROUP|ORDER|HAVING|$)'
        for match in re.finditer(from_pattern, sql_upper):
            table_name, alias = match.groups()
            if alias not in self.SQL_KEYWORDS:
                aliases[alias] = table_name.split('.')[-1]
        
        join_pattern = r'\bJOIN\s+(\w+(?:\.\w+)?)\s+(\w+)\s+ON'
        for match in re.finditer(join_pattern, sql_upper):
            table_name, alias = match.groups()
            if alias not in self.SQL_KEYWORDS:
                aliases[alias] = table_name.split('.')[-1]
        
        as_pattern = r'\b(\w+(?:\.\w+)?)\s+AS\s+(\w+)\b'
        for match in re.finditer(as_pattern, sql_upper):
            table_name, alias = match.groups()
            if alias not in self.SQL_KEYWORDS:
                aliases[alias] = table_name.split('.')[-1]
        
        return aliases
    
    def check_bracket_balance(self, content: str, filename: str) -> Tuple[bool, str]:
        """检查括号平衡"""
        # 移除注释和字符串内容
        content = self._remove_comments(content)
        content = self._remove_string_literals(content)
        
        stack = []
        pairs = {'(': ')', '[': ']', '{': '}'}
        
        for i, char in enumerate(content):
            if char in pairs:
                stack.append((char, i))
            elif char in pairs.values():
                if not stack:
                    return False, f"位置 {i}: 多余的 '{char}'"
                last_char, last_pos = stack.pop()
                if pairs.get(last_char) != char:
                    return False, f"位置 {last_pos}: '{last_char}' 与 '{char}' 不匹配"
        
        if stack:
            last_char, last_pos = stack[-1]
            return False, f"位置 {last_pos}: '{last_char}' 未闭合"
        
        return True, ""
    
    def check_quote_balance(self, content: str, filename: str) -> Tuple[bool, str]:
        """检查引号平衡"""
        content = self._remove_comments(content)
        
        single_quote_count = 0
        double_quote_count = 0
        i = 0
        
        while i < len(content):
            char = content[i]
            
            # 跳过转义字符
            if char == '\\' and i + 1 < len(content):
                i += 2
                continue
            
            if char == "'":
                single_quote_count += 1
            elif char == '"':
                double_quote_count += 1
            
            i += 1
        
        if single_quote_count % 2 != 0:
            return False, f"单引号未闭合 (数量: {single_quote_count})"
        if double_quote_count % 2 != 0:
            return False, f"双引号未闭合 (数量: {double_quote_count})"
        
        return True, ""
    
    def check_keyword_spelling(self, content: str, filename: str) -> Tuple[bool, List[str]]:
        """
        检查关键字拼写 (v2.0.0: 基于AST识别别名，不再使用Levenshtein距离)
        
        改进:
        1. 使用AST解析准确识别所有表/CTE/子查询别名
        2. 只检查不在别名列表中的token
        3. 只报告COMMON_TYPOS中明确定义的拼写错误
        4. 不再使用Levenshtein距离模糊匹配（解决acts→ACOS等误报）
        """
        content = self._remove_comments(content)
        content = self._remove_string_literals(content)
        
        # 使用AST提取所有别名
        aliases = self.extract_aliases(content)
        alias_set = set(aliases.keys())
        
        # 常见的 schema 名和表别名前缀（不应被误报为拼写错误）
        schema_prefixes = {'SDORD', 'SDPAY', 'SDLOG', 'SDMAR', 'SDREF', 'SLORD',
                          'DIM', 'DWD', 'DWB', 'DWS', 'ODS', 'STG', 'TMP',
                          'DWI', 'DWA', 'DWR', 'DM', 'ADS',
                          'SHA', 'PAY', 'ORD', 'LOG', 'REF', 'COUP', 'ACT'}
        
        # 提取可能的标识符
        tokens = re.findall(r'\b[A-Z_]{2,}\b', content.upper())
        
        typos = []
        for token in tokens:
            # 跳过已知的 schema 前缀
            if token in schema_prefixes:
                continue
            
            # 跳过AST识别出的别名 (v2.0.0 核心改进)
            if token in alias_set:
                continue
            
            # 跳过可能的前缀（以 _ 结尾的通常是别名）
            if token.endswith('_'):
                continue
            
            # 跳过已知的关键字
            if token in self.SQL_KEYWORDS:
                continue
            
            # 只检查明确定义的拼写错误 (不再使用Levenshtein距离!)
            if token in self.COMMON_TYPOS:
                typos.append(f"'{token}' 应为 '{self.COMMON_TYPOS[token]}'")
        
        return len(typos) == 0, typos
    
    def check_insert_field_match(self, content: str, filename: str) -> Tuple[bool, str]:
        """检查 INSERT 字段数量匹配（支持 CTE 和复杂 SELECT）"""
        content = self._remove_comments(content)
        
        # 匹配 INSERT INTO table (fields) SELECT ... 模式
        # 支持: INSERT INTO ... SELECT 和 WITH ... AS (...) INSERT INTO ... SELECT
        insert_pattern = r'INSERT\s+INTO\s+\S+\s*\(([^)]+)\)\s*SELECT'
        match = re.search(insert_pattern, content, re.IGNORECASE | re.DOTALL)
        
        if not match:
            # 可能是没有字段列表的 INSERT，不算错误
            return True, ""
        
        insert_fields = match.group(1)
        field_count = len([f.strip() for f in insert_fields.split(',') if f.strip()])
        
        # 提取 INSERT 后的主 SELECT 语句（处理 CTE 情况）
        # 找到 INSERT ... SELECT 后面的内容
        insert_pos = match.end()
        after_select = content[insert_pos:].strip()
        
        # 处理 CTE: 如果 SELECT 后面有 FROM，提取到 FROM 之前
        # 如果是嵌套 SELECT 或子查询，需要更智能的解析
        select_fields = self._extract_main_select_fields(after_select)
        
        if not select_fields:
            return False, "无法解析 SELECT 语句"
        
        # 计算选择字段数量（处理函数和嵌套括号）
        select_count = self._count_select_fields(select_fields)
        
        if field_count != select_count:
            return False, f"INSERT 字段数 ({field_count}) 与 SELECT 字段数 ({select_count}) 不匹配"
        
        return True, ""
    
    def check_case_when_else(self, content: str, filename: str) -> Tuple[bool, str]:
        missing_else = []
        content = self._remove_comments(content)
        
        cases = list(re.finditer(r'\bCASE\b', content, re.IGNORECASE))
        
        for case_match in cases:
            start = case_match.start()
            depth = 1
            end = start
            i = start + 4
            
            while i < len(content) and depth > 0:
                if re.match(r'\bCASE\b', content[i:], re.IGNORECASE):
                    depth += 1
                    i += 4
                elif re.match(r'\bEND\b', content[i:], re.IGNORECASE):
                    depth -= 1
                    if depth == 0:
                        end = i + 3
                    i += 3
                else:
                    i += 1
            
            if end <= start:
                continue
            
            case_block = content[start:end]
            if not re.search(r'\bELSE\b', case_block, re.IGNORECASE):
                line_num = content[:start].count('\n') + 1
                missing_else.append(f"行{line_num}")
        
        if missing_else:
            return False, f"CASE语句缺少ELSE分支: {', '.join(missing_else[:5])}"
        return True, ""
    
    def check_join_on_condition(self, content: str, filename: str) -> Tuple[bool, str]:
        missing_on = []
        content = self._remove_comments(content)
        
        lines = content.split('\n')
        cte_names = set()
        
        cte_pattern = r'^\s*(\w+)\s+AS\s*\('
        for line in lines:
            match = re.match(cte_pattern, line, re.IGNORECASE)
            if match:
                cte_names.add(match.group(1).upper())
        
        join_pattern = r'\b(?:LEFT|RIGHT|INNER|OUTER|FULL|CROSS)?\s*JOIN\s+(\w+(?:\.\w+)?)'
        joins = re.finditer(join_pattern, content, re.IGNORECASE)
        
        for join_match in joins:
            table = join_match.group(1).split('.')[-1]
            
            if table.upper() in cte_names:
                continue
            
            after_join = content[join_match.end():]
            on_search = re.search(r'\bON\b', after_join[:500], re.IGNORECASE)
            
            if not on_search:
                before_on = after_join[:100].replace('\n', ' ').strip()
                if len(before_on) > 50:
                    before_on = before_on[:50] + '...'
                line_num = content[:join_match.start()].count('\n') + 1
                missing_on.append(f"{table}(行{line_num})")
        
        if missing_on:
            return False, f"JOIN缺少ON条件: {', '.join(missing_on[:5])}"
        return True, ""
    
    def check_select_star(self, content: str, filename: str) -> Tuple[bool, str]:
        star_usage = []
        content = self._remove_comments(content)
        
        lines = content.split('\n')
        cte_names = set()
        
        cte_pattern = r'^\s*(\w+)\s+AS\s*\('
        for line in lines:
            match = re.match(cte_pattern, line, re.IGNORECASE)
            if match:
                cte_names.add(match.group(1).upper())
        
        source_table_pattern = r'\bFROM\s+(\w+(?:\.\w+)?)'
        
        for i, line in enumerate(lines, 1):
            if re.search(r'SELECT\s+\*\s+FROM', line, re.IGNORECASE):
                table_match = re.search(source_table_pattern, line, re.IGNORECASE)
                if table_match:
                    table = table_match.group(1).split('.')[-1]
                    if table.upper() in cte_names:
                        continue
                
                star_usage.append(f"行{i}")
        
        if star_usage:
            return False, f"使用了SELECT *: {', '.join(star_usage[:5])}"
        return True, ""
    
    def check_ddl_distributed_syntax(self, content: str, filename: str) -> Tuple[bool, str]:
        """
        检查 DDL 中的 DISTRIBUTED BY 语法（v2.1.0 新增）
        
        检查项:
        1. DISTRIBUTE BY 应为 DISTRIBUTED BY
        2. 分布键语法应为 DISTRIBUTED BY HASH(field) 或 DISTRIBUTED BY REPLICATION
        3. 分布键字段不应使用单引号包裹
        """
        issues = []
        content_upper = content.upper()
        
        # 检查 1: DISTRIBUTE BY 应为 DISTRIBUTED BY
        if re.search(r'\bDISTRIBUTE\s+BY\b', content_upper):
            # 检查是否是 DISTRIBUTED（完整拼写）
            if not re.search(r'\bDISTRIBUTED\s+BY\b', content_upper):
                line_num = content[:re.search(r'\bDISTRIBUTE\s+BY\b', content_upper).start()].count('\n') + 1
                issues.append(f"行{line_num}: 应使用 'DISTRIBUTED BY' 而非 'DISTRIBUTE BY'")
        
        # 检查 2: 分布键字段不应使用单引号
        if re.search(r"DISTRIBUTED\s+BY\s*\(['\"]", content, re.IGNORECASE):
            match = re.search(r"DISTRIBUTED\s+BY\s*\(['\"]", content, re.IGNORECASE)
            line_num = content[:match.start()].count('\n') + 1
            issues.append(f"行{line_num}: 分布键字段不应使用引号，应为 DISTRIBUTED BY HASH(field)")
        
        # 检查 3: 分布键应有 HASH 或 REPLICATION 关键字
        if re.search(r'\bDISTRIBUTED\s+BY\b', content_upper):
            if not re.search(r'\bDISTRIBUTED\s+BY\s+(HASH|REPLICATION)\b', content_upper):
                match = re.search(r'\bDISTRIBUTED\s+BY\b', content_upper)
                line_num = content[:match.start()].count('\n') + 1
                issues.append(f"行{line_num}: 分布键应指定分布方式，如 DISTRIBUTED BY HASH(field)")
        
        if issues:
            return False, "; ".join(issues)
        return True, ""
    
    def check_inline_comment(self, content: str, filename: str) -> Tuple[bool, str]:
        """
        检查 DDL 中是否使用了内联 COMMENT（MySQL 语法）
        
        DWS (PostgreSQL) 不支持内联 COMMENT 语法，如:
            col1 VARCHAR(10) COMMENT 'xxx'
        必须使用独立的 COMMENT ON 语句:
            COMMENT ON COLUMN table.col1 IS 'xxx';
        """
        issues = []
        
        # 找到 CREATE TABLE 所在行号，以及对应的闭合括号行号
        in_create_table = False
        paren_depth = 0
        create_start_line = 0
        
        for line_num, line in enumerate(content.split('\n'), 1):
            stripped = line.strip().upper()
            
            if re.match(r'CREATE\s+TABLE\b', stripped):
                in_create_table = True
                create_start_line = line_num
                paren_depth = stripped.count('(') - stripped.count(')')
                if paren_depth <= 0:
                    in_create_table = False
                continue
            
            if in_create_table:
                paren_depth += stripped.count('(') - stripped.count(')')
                if paren_depth <= 0:
                    in_create_table = False
                    continue
                
                # 在 CREATE TABLE 括号内，检查是否有内联 COMMENT
                # 匹配: field_name TYPE[(size)] COMMENT 'xxx'
                if re.search(r'COMMENT\s+[\'"]', stripped):
                    pattern = r"^\s*\S+\s+\w+(?:\([^)]*\))?\s+COMMENT\s+['\"].*?['\"]"
                    match = re.match(pattern, line, re.IGNORECASE)
                    if match:
                        preview = match.group(0).strip()[:60]
                        preview = preview + ('...' if len(match.group(0).strip()) > 60 else '')
                        issues.append(f"行{line_num}: 发现内联 COMMENT — {preview}")
        
        if issues:
            return False, '; '.join(issues) + '。DWS 不支持内联 COMMENT，请改用 COMMENT ON COLUMN 语句。'
        return True, ''
    
    def check_duplicate_fields_ddl(self, content: str, filename: str) -> Tuple[bool, str]:
        field_pattern = r'^\s+([a-zA-Z_][a-zA-Z0-9_]*)\s+[A-Z]+'
        fields = re.findall(field_pattern, content, re.MULTILINE)
        from collections import Counter
        duplicates = [f for f, c in Counter(fields).items() if c > 1]
        return len(duplicates) == 0, f'发现重复字段: {", ".join(duplicates)}' if duplicates else '无字段重复'
    
    def check_audit_field_types(self, content: str, filename: str) -> Tuple[bool, str]:
        """
        检查审计字段类型一致性
        
        检查项:
        1. del_flag 应为 NVARCHAR(1)
        2. crt_cycle_id 应为 BIGINT
        3. last_upd_cycle_id 应为 BIGINT
        4. dw_last_update_date 应为 TIMESTAMP(0) WITHOUT TIME ZONE
        """
        issues = []
        
        # 检查 del_flag 类型
        del_match = re.search(r'del_flag\s+(\w+(?:\(\d+(?:,\d+)?\))?(?:\s+WITHOUT\s+TIME\s+ZONE)?)', content, re.IGNORECASE)
        if del_match:
            type_str = del_match.group(1).upper()
            if type_str != 'NVARCHAR(1)':
                issues.append(f"del_flag 类型应为 NVARCHAR(1)，当前为 {type_str}")
        
        # 检查 crt_cycle_id 类型
        crt_match = re.search(r'crt_cycle_id\s+(\w+(?:\(\d+(?:,\d+)?\))?)', content, re.IGNORECASE)
        if crt_match:
            type_str = crt_match.group(1).upper()
            if type_str != 'BIGINT':
                issues.append(f"crt_cycle_id 类型应为 BIGINT，当前为 {type_str}")
        
        # 检查 last_upd_cycle_id 类型
        upd_match = re.search(r'last_upd_cycle_id\s+(\w+(?:\(\d+(?:,\d+)?\))?)', content, re.IGNORECASE)
        if upd_match:
            type_str = upd_match.group(1).upper()
            if type_str != 'BIGINT':
                issues.append(f"last_upd_cycle_id 类型应为 BIGINT，当前为 {type_str}")
        
        # 检查 dw_last_update_date 类型
        dt_match = re.search(r'dw_last_update_date\s+(\w+(?:\(\d+(?:,\d+)?\))?(?:\s+WITHOUT\s+TIME\s+ZONE)?)', content, re.IGNORECASE)
        if dt_match:
            type_str = dt_match.group(1).upper()
            if type_str != 'TIMESTAMP(0) WITHOUT TIME ZONE':
                issues.append(f"dw_last_update_date 类型应为 TIMESTAMP(0) WITHOUT TIME ZONE，当前为 {type_str}")
        
        if issues:
            return False, "; ".join(issues)
        return True, ""
    
    def check_ddl_no_drop_table(self, content: str, filename: str) -> Tuple[bool, str]:
        """DDL 中禁止 DROP TABLE，必须使用 CREATE TABLE IF NOT EXISTS"""
        issues = []
        content_upper = content.upper()

        if re.search(r'\bDROP\s+TABLE\b', content_upper):
            issues.append("DDL 中禁止使用 DROP TABLE，应使用 CREATE TABLE IF NOT EXISTS")

        create_match = re.search(r'\bCREATE\s+TABLE\b', content_upper)
        if create_match and not re.search(r'\bCREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\b', content_upper):
            issues.append("必须使用 CREATE TABLE IF NOT EXISTS")

        if issues:
            return False, "; ".join(issues)
        return True, ""

    def check_ddl_to_group(self, content: str, filename: str) -> Tuple[bool, str]:
        """DDL 必须指定 TO GROUP 逻辑集群，且值与 schema 匹配"""
        issues = []
        content_upper = content.upper()

        has_create = re.search(r'\bCREATE\s+(TABLE|VIEW)\b', content_upper)
        if has_create:
            if not re.search(r'\bTO\s+GROUP\b', content_upper):
                issues.append("缺少 TO GROUP 逻辑集群指定")
            else:
                group_match = re.search(r'TO\s+GROUP\s+"([^"]+)"', content, re.IGNORECASE)
                if group_match:
                    group_value = group_match.group(1)
                    schema_match = re.search(
                        r'CREATE\s+(?:TABLE|VIEW)\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\.(\w+)',
                        content, re.IGNORECASE
                    )
                    if schema_match:
                        schema = schema_match.group(1)
                        expected = "gtoup_version1" if re.search(r'drt', schema, re.IGNORECASE) else "LC_DW1"
                        if group_value != expected:
                            issues.append(
                                f"逻辑集群不匹配: schema='{schema}' 期望 '{expected}'，实际 '{group_value}'")

        if issues:
            return False, "; ".join(issues)
        return True, ""

    def _extract_main_select_fields(self, after_select_content: str) -> Optional[str]:
        """从 SELECT 后的内容中提取主 SELECT 的字段列表"""
        # 找到第一个 FROM 关键字（不在括号内的）
        depth = 0
        from_pos = -1
        
        for i, char in enumerate(after_select_content):
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
            elif depth == 0:
                # 检查是否是 FROM 关键字
                remaining = after_select_content[i:].upper()
                if remaining.startswith('FROM ') or remaining.startswith('FROM\n') or remaining.startswith('FROM\t'):
                    from_pos = i
                    break
        
        if from_pos == -1:
            # 没有找到 FROM，可能整个内容就是字段列表
            return after_select_content.strip()
        
        return after_select_content[:from_pos].strip()
    
    def _count_select_fields(self, select_clause: str) -> int:
        """计算 SELECT 字段数量，正确处理 CASE WHEN 内部逗号"""
        count = 0
        parenthesis_depth = 0
        case_nesting_depth = 0
        current_field = ""
        i = 0
        clause_len = len(select_clause)
        
        while i < clause_len:
            char = select_clause[i]
            
            is_case_start = (
                parenthesis_depth == 0 and
                select_clause[i:i+4].upper() == 'CASE' and
                (i == 0 or not select_clause[i-1].isalnum()) and
                (i+4 >= clause_len or not select_clause[i+4].isalnum())
            )
            if is_case_start:
                case_nesting_depth += 1
                current_field += char
                i += 1
                continue
            
            is_case_end = (
                case_nesting_depth > 0 and
                select_clause[i:i+3].upper() == 'END' and
                (i == 0 or not select_clause[i-1].isalnum()) and
                (i+3 >= clause_len or not select_clause[i+3].isalnum())
            )
            if is_case_end:
                case_nesting_depth -= 1
                current_field += char
                i += 1
                continue
            
            if char == '(':
                parenthesis_depth += 1
                current_field += char
            elif char == ')':
                parenthesis_depth -= 1
                current_field += char
            elif char == ',' and parenthesis_depth == 0 and case_nesting_depth == 0:
                if current_field.strip():
                    count += 1
                current_field = ""
            else:
                current_field += char
            
            i += 1
        
        if current_field.strip():
            count += 1
        
        return count
    
    def check_ddl_etl_consistency(self, ddl_dir: str, etl_dir: str) -> Tuple[bool, List[str]]:
        """检查 DDL 和 ETL 字段一致性"""
        issues = []
        
        # 解析所有 DDL 文件
        ddl_fields = {}
        for ddl_file in Path(ddl_dir).glob('*.sql'):
            table_name, fields = self._parse_ddl(ddl_file.read_text())
            if table_name and fields:
                ddl_fields[table_name] = fields
        
        # 检查 ETL 文件
        for etl_file in Path(etl_dir).glob('*.sql'):
            content = etl_file.read_text()
            
            # 提取 INSERT 目标表
            insert_match = re.search(r'INSERT\s+INTO\s+(\S+)', content, re.IGNORECASE)
            if not insert_match:
                continue
            
            target_table = insert_match.group(1).lower()
            
            # 查找对应的 DDL
            matching_ddl = None
            for table_name in ddl_fields:
                if table_name.lower() in target_table or target_table in table_name.lower():
                    matching_ddl = table_name
                    break
            
            if matching_ddl:
                # 提取 ETL 中的字段（先移除注释）
                clean_content = self._remove_comments(content)
                fields_match = re.search(r'INSERT\s+INTO\s+\S+\s*\(([^)]+)\)', clean_content, re.IGNORECASE)
                if fields_match:
                    # 清理字段名：移除空白和换行
                    raw_fields = fields_match.group(1)
                    etl_fields = []
                    for f in raw_fields.split(','):
                        cleaned = f.strip().lower()
                        # 跳过空字段和注释行
                        if cleaned and not cleaned.startswith('--'):
                            etl_fields.append(cleaned)
                    
                    ddl_field_names = [f.lower() for f in ddl_fields[matching_ddl]]
                    
                    # 检查字段是否都在 DDL 中
                    for field in etl_fields:
                        if field not in ddl_field_names:
                            issues.append(f"{etl_file.name}: 字段 '{field}' 不在 DDL 定义中")
        
        return len(issues) == 0, issues
    
    def _parse_ddl(self, content: str) -> Tuple[Optional[str], List[str]]:
        """解析 DDL 提取表名和字段"""
        # 只保留 CREATE TABLE 语句部分（去除 COMMENT ON 等后续语句）
        # 找到 CREATE TABLE 和第一个 ) WITH 之间的内容
        create_match = re.search(r'CREATE\s+TABLE\s+(\S+)\s*\(', content, re.IGNORECASE)
        if not create_match:
            return None, []
        
        table_name = create_match.group(1)
        
        # 从 CREATE TABLE ( 后面开始，找到匹配的 ) WITH
        start_pos = create_match.end()
        
        # 使用括号匹配找到正确的结束位置
        depth = 1
        end_pos = start_pos
        for i in range(start_pos, len(content)):
            char = content[i]
            if char == '(':
                depth += 1
            elif char == ')':
                depth -= 1
                if depth == 0:
                    end_pos = i
                    break
        
        fields_section = content[start_pos:end_pos]
        fields = []
        
        # 解析字段定义
        # 字段格式: field_name field_type [constraints]
        # 跳过: PRIMARY KEY, FOREIGN KEY, UNIQUE, CHECK, CONSTRAINT 等约束定义
        constraint_keywords = ('PRIMARY', 'FOREIGN', 'UNIQUE', 'CHECK', 'CONSTRAINT', 
                               'INDEX', 'KEY', 'REFERENCES')
        
        for line in fields_section.split('\n'):
            line = line.strip().rstrip(',')
            
            # 跳过空行和注释
            if not line or line.startswith('--'):
                continue
            
            # 跳过约束定义
            upper_line = line.upper()
            if upper_line.startswith(constraint_keywords):
                continue
            
            # 匹配字段定义: 字段名 后面跟着类型
            # 字段名: 字母、数字、下划线
            # 类型: VARCHAR, NVARCHAR2, VARCHAR2, INT, BIGINT, DECIMAL, DATE, TIMESTAMP 等
            field_match = re.match(r'^(\w+)\s+(?:VARCHAR2?|NVARCHAR2|CHAR|NCHAR|INT|INTEGER|BIGINT|SMALLINT|TINYINT|'
                                   r'DECIMAL|NUMERIC|NUMBER|FLOAT|DOUBLE|REAL|DATE|TIME|TIMESTAMP|TIMESTAMPTZ|'
                                   r'BOOLEAN|BOOL|TEXT|CLOB|BLOB|BYTEA|JSON|JSONB|UUID|SERIAL|BIGSERIAL|SMALLSERIAL)', 
                                   line, re.IGNORECASE)
            if field_match:
                fields.append(field_match.group(1))
        
        return table_name, fields
    
    def _remove_comments(self, content: str) -> str:
        """移除 SQL 注释"""
        # 移除单行注释
        content = re.sub(r'--[^\n]*', '', content)
        # 移除多行注释
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        return content
    
    def _remove_string_literals(self, content: str) -> str:
        """移除字符串字面量"""
        content = re.sub(r"'[^']*'", "''", content)
        content = re.sub(r'"[^"]*"', '""', content)
        return content
    
    def _levenshtein_distance(self, s1: str, s2: str) -> int:
        """计算编辑距离"""
        if len(s1) < len(s2):
            return self._levenshtein_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]
    
    def validate_file(self, filepath: str, file_type: str) -> Dict:
        """验证单个文件"""
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        filename = os.path.basename(filepath)
        results = {
            'file': filename,
            'type': file_type,
            'checks': []
        }
        
        # 1. 括号平衡检查
        passed, msg = self.check_bracket_balance(content, filename)
        results['checks'].append({
            'name': '括号平衡',
            'passed': passed,
            'message': msg if not passed else '括号匹配正确'
        })
        
        # 2. 引号平衡检查
        passed, msg = self.check_quote_balance(content, filename)
        results['checks'].append({
            'name': '引号平衡',
            'passed': passed,
            'message': msg if not passed else '引号匹配正确'
        })
        
        # 3. 关键字拼写检查
        passed, typos = self.check_keyword_spelling(content, filename)
        results['checks'].append({
            'name': '关键字拼写',
            'passed': passed,
            'message': '无拼写错误' if passed else '; '.join(typos)
        })
        
        # 4. 内联 COMMENT 检查 (仅 DDL 文件)
        if file_type == 'DDL':
            passed, msg = self.check_inline_comment(content, filename)
            results['checks'].append({
                'name': '内联COMMENT检查',
                'passed': passed,
                'message': msg if not passed else '未使用内联COMMENT'
            })
        
        # 5. 字段重复检查 (仅 DDL 文件)
        if file_type == 'DDL':
            passed, msg = self.check_duplicate_fields_ddl(content, filename)
            results['checks'].append({
                'name': '字段重复检查',
                'passed': passed,
                'message': msg
            })
            
            # 6. DROP TABLE / IF NOT EXISTS 检查 (仅 DDL 文件)
            passed, msg = self.check_ddl_no_drop_table(content, filename)
            results['checks'].append({
                'name': 'DDL建表规范',
                'passed': passed,
                'message': msg if not passed else '使用CREATE IF NOT EXISTS，无DROP TABLE'
            })
            
            # 7. TO GROUP 逻辑集群检查 (仅 DDL 文件)
            passed, msg = self.check_ddl_to_group(content, filename)
            results['checks'].append({
                'name': 'TO GROUP逻辑集群',
                'passed': passed,
                'message': msg if not passed else 'TO GROUP指定正确'
            })
        
        # 5. INSERT 字段匹配 (仅 ETL 文件)
        if file_type == 'ETL':
            passed, msg = self.check_insert_field_match(content, filename)
            results['checks'].append({
                'name': 'INSERT字段匹配',
                'passed': passed,
                'message': msg if not passed else '字段数量匹配'
            })
            
            # 5. CASE WHEN 完整性检查 (仅 ETL 文件)
            passed, msg = self.check_case_when_else(content, filename)
            results['checks'].append({
                'name': 'CASE WHEN完整性',
                'passed': passed,
                'message': msg if not passed else '所有CASE都有ELSE分支'
            })
            
            # 6. JOIN ON 条件检查 (仅 ETL 文件)
            passed, msg = self.check_join_on_condition(content, filename)
            results['checks'].append({
                'name': 'JOIN ON条件',
                'passed': passed,
                'message': msg if not passed else '所有JOIN都有ON条件'
            })
            
            # 7. SELECT * 检查 (仅 ETL 文件)
            passed, msg = self.check_select_star(content, filename)
            results['checks'].append({
                'name': 'SELECT * 检查',
                'passed': passed,
                'message': msg if not passed else '未使用SELECT *'
            })
        
        return results
    
    def _extract_target_table_from_path(self, ddl_dir: str) -> str:
        """从DDL目录路径推断目标表名"""
        ddl_path = Path(ddl_dir)
        
        # 尝试从路径中提取表名 (docs/output/{table_name}/04_ddl)
        parts = ddl_path.parts
        for i, part in enumerate(parts):
            if part == 'output' and i + 1 < len(parts):
                return parts[i + 1]
        
        # 尝试从DDL文件中提取
        if ddl_path.exists():
            for sql_file in sorted(ddl_path.glob('*.sql')):
                content = sql_file.read_text()
                match = re.search(r'CREATE\s+TABLE\s+(\S+)\s*\(', content, re.IGNORECASE)
                if match:
                    # 返回表名（去除schema前缀）
                    return match.group(1).split('.')[-1]
        
        return "未知表"
    
    def generate_report(self, ddl_dir: str, etl_dir: str, output_path: str, target_table: str = None):
        """生成测试报告
        
        Args:
            ddl_dir: DDL文件目录
            etl_dir: ETL文件目录  
            output_path: 输出报告路径
            target_table: 目标表名（可选，默认从路径推断）
        """
        # 如果未指定表名，从路径推断
        if target_table is None:
            target_table = self._extract_target_table_from_path(ddl_dir)
        
        all_results = []
        
        # 验证 DDL 文件
        ddl_path = Path(ddl_dir)
        if ddl_path.exists():
            for sql_file in sorted(ddl_path.glob('*.sql')):
                result = self.validate_file(str(sql_file), 'DDL')
                all_results.append(result)
        
        # 验证 ETL 文件
        etl_path = Path(etl_dir)
        if etl_path.exists():
            for sql_file in sorted(etl_path.glob('*.sql')):
                result = self.validate_file(str(sql_file), 'ETL')
                all_results.append(result)
        
        # DDL-ETL 一致性检查
        consistency_passed, consistency_issues = self.check_ddl_etl_consistency(ddl_dir, etl_dir)
        
        # 统计结果
        total_checks = 0
        passed_checks = 0
        failed_checks = 0
        
        for result in all_results:
            for check in result['checks']:
                total_checks += 1
                if check['passed']:
                    passed_checks += 1
                else:
                    failed_checks += 1
        
        # 加上一致性检查
        total_checks += 1
        if consistency_passed:
            passed_checks += 1
        else:
            failed_checks += 1
        
        # 生成报告
        report = self._format_report(all_results, consistency_passed, consistency_issues,
                                      total_checks, passed_checks, failed_checks, target_table)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"测试报告已生成: {output_path}")
        return failed_checks == 0
    
    def _format_report(self, results: List[Dict], consistency_passed: bool, 
                       consistency_issues: List[str], total: int, passed: int, failed: int,
                       target_table: str) -> str:
        """格式化报告"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        ddl_count = sum(1 for r in results if r['type'] == 'DDL')
        etl_count = sum(1 for r in results if r['type'] == 'ETL')
        
        report = f"""# ETL 测试报告

**测试时间**: {now}
**测试对象**: {target_table}

---

## 1. 测试概览

| 指标 | 数量 |
|------|------|
| DDL文件数 | {ddl_count} |
| ETL文件数 | {etl_count} |
| 通过项 | {passed} |
| 失败项 | {failed} |
| 警告项 | 0 |

**测试结果**: {'✅ 全部通过' if failed == 0 else '❌ 存在失败项'}

---

## 2. 测试详情

### 2.1 通过项 ✅

"""
        # 添加通过的检查项
        for result in results:
            for check in result['checks']:
                if check['passed']:
                    report += f"| {check['name']} - {result['file']} | {check['message']} |\n"
        
        if consistency_passed:
            report += "| DDL-ETL一致性 | DDL与ETL字段一致 |\n"
        
        report += """
### 2.2 失败项 ❌

"""
        # 添加失败的检查项
        has_failed = False
        for result in results:
            for check in result['checks']:
                if not check['passed']:
                    has_failed = True
                    report += f"| {check['name']} - {result['file']} | {check['message']} |\n"
        
        if not consistency_passed:
            has_failed = True
            for issue in consistency_issues:
                report += f"| DDL-ETL一致性 | {issue} |\n"
        
        if not has_failed:
            report += "无\n"
        
        report += """
### 2.3 警告项 ⚠️

无

---

## 3. 测试文件清单

### 3.1 DDL 文件

"""
        for result in results:
            if result['type'] == 'DDL':
                report += f"- `{result['file']}`\n"
        
        report += """
### 3.2 ETL 文件

"""
        for result in results:
            if result['type'] == 'ETL':
                report += f"- `{result['file']}`\n"
        
        report += """
---

## 4. 测试项目说明

| 测试项 | 描述 |
|--------|------|
| 括号平衡检查 | 检查 SQL 语句中括号是否正确闭合 |
| 引号平衡检查 | 检查字符串引号是否正确闭合 |
| 关键字拼写检查 | 检查 SQL 关键字是否存在拼写错误 |
| INSERT字段匹配 | 检查 INSERT 和 SELECT 字段数量是否一致 |
| DDL-ETL一致性 | 检查 ETL 写入字段与 DDL 定义是否一致 |

---

*报告生成完毕*
"""
        return report

    def validate_single_file(self, filepath: str, file_type: str, output_path: str = None) -> Dict:
        """
        验证单个 SQL 文件（v2.3.0 新增）
        
        Args:
            filepath: SQL 文件路径
            file_type: 文件类型 ('ddl' 或 'etl')
            output_path: 输出报告路径（可选，不指定则打印到控制台）
        
        Returns:
            验证结果字典
        """
        result = self.validate_file(filepath, file_type.upper())
        
        # 生成单文件报告
        report = self._format_single_file_report(result, filepath, file_type)
        
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"单文件检查报告已生成: {output_path}")
        else:
            print(report)
        
        # 返回是否全部通过
        all_passed = all(check['passed'] for check in result['checks'])
        return {
            'file': filepath,
            'type': file_type,
            'passed': all_passed,
            'checks': result['checks']
        }
    
    def _format_single_file_report(self, result: Dict, filepath: str, file_type: str) -> str:
        """格式化单文件报告"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        filename = os.path.basename(filepath)
        
        passed_count = sum(1 for c in result['checks'] if c['passed'])
        failed_count = sum(1 for c in result['checks'] if not c['passed'])
        
        report = f"""# SQL 语法检查报告（单文件模式）

**检查时间**: {now}
**文件路径**: {filepath}
**文件类型**: {file_type.upper()}

---

## 检查结果

| 指标 | 数量 |
|------|------|
| 通过项 | {passed_count} |
| 失败项 | {failed_count} |

**检查结论**: {'✅ 全部通过' if failed_count == 0 else '❌ 存在失败项'}

---

## 检查详情

### 通过项 ✅

"""
        for check in result['checks']:
            if check['passed']:
                report += f"| {check['name']} | {check['message']} |\n"
        
        report += """
### 失败项 ❌

"""
        has_failed = False
        for check in result['checks']:
            if not check['passed']:
                has_failed = True
                report += f"| {check['name']} | {check['message']} |\n"
        
        if not has_failed:
            report += "无\n"
        
        report += """
---

*报告生成完毕*
"""
        return report


def main():
    parser = argparse.ArgumentParser(description='DWS ETL SQL 语法检查工具')
    
    # 互斥参数组：目录模式 vs 单文件模式
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--ddl-dir', help='DDL 文件目录（目录模式）')
    mode_group.add_argument('--file', '-f', help='单个 SQL 文件路径（单文件模式）')
    
    # 目录模式参数
    parser.add_argument('--etl-dir', help='ETL 文件目录（目录模式，与 --ddl-dir 配合使用）')
    parser.add_argument('--output', help='输出报告路径')
    parser.add_argument('--target-table', '-t', help='目标表名（可选，默认从路径推断）')
    
    # 单文件模式参数
    parser.add_argument('--type', choices=['ddl', 'etl'], help='文件类型（单文件模式，与 --file 配合使用）')
    
    args = parser.parse_args()
    
    validator = SQLValidator()
    
    # 单文件模式
    if args.file:
        if not args.type:
            parser.error("单文件模式需要指定 --type (ddl 或 etl)")
        
        output_path = args.output  # 可选
        result = validator.validate_single_file(args.file, args.type, output_path)
        return 0 if result['passed'] else 1
    
    # 目录模式
    else:
        if not args.ddl_dir or not args.etl_dir:
            parser.error("目录模式需要同时指定 --ddl-dir 和 --etl-dir")
        if not args.output:
            parser.error("目录模式需要指定 --output")
        
        success = validator.generate_report(args.ddl_dir, args.etl_dir, args.output, args.target_table)
        return 0 if success else 1


if __name__ == '__main__':
    exit(main())
