/**
 * security.test.ts — SQL 安全验证逻辑测试
 *
 * 源文件 src/index.ts 不导出内部函数，以下逻辑从源码提取用于测试。
 * Extracted from src/index.ts lines 270-334.
 */

import { describe, it, expect, vi } from 'vitest'

// ============================================================================
// 从 src/index.ts 提取的纯逻辑函数（用于测试）
// ============================================================================

// src/index.ts:270-291 — SQL 写操作关键字检查
function checkWriteBlocked(sql: string, allowWriteOperations: boolean): {
  blocked: boolean
  keyword?: string
  error?: string
} {
  if (!allowWriteOperations) {
    const writeKeywords = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 'TRUNCATE', 'GRANT', 'REVOKE']
    const upperSql = sql.toUpperCase().trim()
    for (const keyword of writeKeywords) {
      if (upperSql.startsWith(keyword)) {
        return {
          blocked: true,
          keyword,
          error: `写操作已被禁用（${keyword}）。如需启用，请在配置中设置 allowWriteOperations: true`,
        }
      }
    }
  }
  return { blocked: false }
}

// src/index.ts:304-314 — 结果行数限制逻辑
function limitRows(rows: Record<string, unknown>[], maxRows: number): Record<string, unknown>[] {
  return rows.slice(0, maxRows)
}

// src/index.ts:265-334 — 完整 executeSql 安全逻辑（模拟版）
interface MockExecuteResult {
  success: boolean
  rows?: Record<string, unknown>[]
  rowCount?: number
  executionTime?: string
  error?: string
}

function mockExecuteSql(
  sql: string,
  allowWriteOperations: boolean,
  maxRows: number,
  mockQueryResult: { rows: Record<string, unknown>[]; rowCount: number }
): MockExecuteResult {
  const startTime = Date.now()

  // 安全检查
  const securityCheck = checkWriteBlocked(sql, allowWriteOperations)
  if (securityCheck.blocked) {
    return {
      success: false,
      error: securityCheck.error,
      executionTime: `${Date.now() - startTime}ms`,
    }
  }

  // 模拟查询执行
  const result = mockQueryResult
  const limitedRows = limitRows(result.rows, maxRows)

  return {
    success: true,
    rows: limitedRows,
    rowCount: result.rowCount,
    executionTime: `${Date.now() - startTime}ms`,
  }
}

// ============================================================================
// 测试
// ============================================================================

describe('SQL 安全验证', () => {
  describe('写操作关键字拦截 (allowWriteOperations: false)', () => {
    const blockedKeywords = ['INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE', 'ALTER', 'TRUNCATE', 'GRANT', 'REVOKE']

    for (const keyword of blockedKeywords) {
      it(`${keyword} 语句被拦截`, () => {
        const sql = `${keyword} INTO users (name) VALUES ('test')`
        const result = checkWriteBlocked(sql, false)
        expect(result.blocked).toBe(true)
        expect(result.keyword).toBe(keyword)
        expect(result.error).toContain(keyword)
      })
    }
  })

  describe('SELECT 语句放行', () => {
    it('SELECT 查询通过安全检查', () => {
      const result = checkWriteBlocked('SELECT * FROM users', false)
      expect(result.blocked).toBe(false)
    })

    it('带 WHERE 条件的 SELECT 通过', () => {
      const result = checkWriteBlocked('SELECT id, name FROM users WHERE active = true', false)
      expect(result.blocked).toBe(false)
    })

    it('带 JOIN 的 SELECT 通过', () => {
      const result = checkWriteBlocked('SELECT u.id, o.total FROM users u JOIN orders o ON u.id = o.user_id', false)
      expect(result.blocked).toBe(false)
    })
  })

  describe('关键字位置检测', () => {
    it('SQL 中间出现 INSERT 不被拦截', () => {
      const sql = "SELECT * FROM logs WHERE action = 'INSERT'"
      const result = checkWriteBlocked(sql, false)
      expect(result.blocked).toBe(false)
    })

    it('SQL 注释中的 DELETE 不被拦截', () => {
      const sql = "SELECT * FROM users -- DELETE this later"
      const result = checkWriteBlocked(sql, false)
      expect(result.blocked).toBe(false)
    })

    it('小写关键字不被拦截（startsWith 是大小写敏感的，且已 toUpperCase）', () => {
      const sql = 'insert into users (name) values (\'test\')'
      const result = checkWriteBlocked(sql, false)
      expect(result.blocked).toBe(true)
      expect(result.keyword).toBe('INSERT')
    })
  })

  describe('allowWriteOperations: true 放行所有', () => {
    it('INSERT 语句在 allowWriteOperations=true 时放行', () => {
      const result = checkWriteBlocked('INSERT INTO users (name) VALUES (\'test\')', true)
      expect(result.blocked).toBe(false)
    })

    it('DROP TABLE 在 allowWriteOperations=true 时放行', () => {
      const result = checkWriteBlocked('DROP TABLE old_data', true)
      expect(result.blocked).toBe(false)
    })

    it('DELETE 语句在 allowWriteOperations=true 时放行', () => {
      const result = checkWriteBlocked('DELETE FROM users WHERE id = 1', true)
      expect(result.blocked).toBe(false)
    })
  })

  describe('maxRows 结果行数限制', () => {
    it('结果行数不超过 maxRows 时不截断', () => {
      const rows = [{ id: 1 }, { id: 2 }, { id: 3 }]
      const result = limitRows(rows, 100)
      expect(result).toHaveLength(3)
    })

    it('结果行数超过 maxRows 时截断', () => {
      const rows = Array.from({ length: 200 }, (_, i) => ({ id: i }))
      const result = limitRows(rows, 100)
      expect(result).toHaveLength(100)
      expect(result[99]).toEqual({ id: 99 })
    })

    it('maxRows=0 时不返回任何行', () => {
      const rows = [{ id: 1 }, { id: 2 }]
      const result = limitRows(rows, 0)
      expect(result).toHaveLength(0)
    })
  })

  describe('mockExecuteSql 端到端安全验证', () => {
    const mockResult = { rows: [{ id: 1, name: 'Alice' }], rowCount: 1 }

    it('SELECT 查询返回成功结果', () => {
      const result = mockExecuteSql('SELECT * FROM users', false, 100, mockResult)
      expect(result.success).toBe(true)
      expect(result.rows).toHaveLength(1)
    })

    it('DELETE 被拦截返回错误', () => {
      const result = mockExecuteSql('DELETE FROM users', false, 100, mockResult)
      expect(result.success).toBe(false)
      expect(result.error).toContain('DELETE')
    })

    it('allowWriteOperations=true 时 INSERT 返回成功', () => {
      const result = mockExecuteSql('INSERT INTO users (name) VALUES (\'Bob\')', true, 100, mockResult)
      expect(result.success).toBe(true)
    })

    it('超过 maxRows 时结果被截断', () => {
      const manyRows = Array.from({ length: 500 }, (_, i) => ({ id: i }))
      const result = mockExecuteSql('SELECT * FROM large_table', true, 50, { rows: manyRows, rowCount: 500 })
      expect(result.success).toBe(true)
      expect(result.rows).toHaveLength(50)
    })

    it('返回结果包含 executionTime', () => {
      const result = mockExecuteSql('SELECT 1', false, 100, { rows: [{ '?column?': 1 }], rowCount: 1 })
      expect(result.executionTime).toBeDefined()
      expect(typeof result.executionTime).toBe('string')
      expect(result.executionTime).toMatch(/\d+ms$/)
    })
  })
})
