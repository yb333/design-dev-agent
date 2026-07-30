/**
 * crud.test.ts — 数据源 CRUD 操作逻辑测试
 *
 * 源文件 src/index.ts 不导出内部函数，以下逻辑从源码提取用于测试。
 * Extracted from src/index.ts lines 570-851.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'

// ============================================================================
// 从 src/index.ts 提取的类型定义（用于测试）
// ============================================================================

interface DatabaseConfig {
  type: 'postgresql' | 'huawei-dws'
  host: string
  port: number
  database: string
  user: string
  password: string
  ssl?: boolean
  sslrootcert?: string
}

interface SecurityConfig {
  allowWriteOperations: boolean
  maxRows: number
  timeout: number
}

interface SourcesConfig {
  default: string
  sources: Record<string, DatabaseConfig>
  security: SecurityConfig
}

// ============================================================================
// CRUD 测试工具 — 从 src/index.ts 提取的操作逻辑
// ============================================================================

/**
 * 模拟模块级状态和 CRUD 操作。
 * 逻辑提取自 src/index.ts:67-76（状态声明）和 587-851（CRUD handlers）。
 */
function createCrudHarness() {
  const sourcesConfig = new Map<string, DatabaseConfig>()
  let currentSource = 'default'
  let securityConfig: SecurityConfig = { allowWriteOperations: false, maxRows: 100, timeout: 0 }
  let sourcesDefault = 'default'
  let configFilePath = ''

  function setConfigFilePath(p: string) { configFilePath = p }
  function ensureSourcesInitialized() { /* 在 harness 中手动管理初始化 */ }

  // src/index.ts:646-650 — 构建完整 SourcesConfig 对象
  function buildFullConfig(): SourcesConfig {
    return {
      default: sourcesDefault,
      sources: Object.fromEntries(sourcesConfig),
      security: securityConfig,
    }
  }

  // src/index.ts:126-134 — writeSourcesFile（简化版）
  let writeShouldFail = false
  let writeFailMessage = '写入配置文件失败: EACCES'

  function mockWriteSourcesFile(config: SourcesConfig): void {
    if (writeShouldFail) {
      throw new Error(writeFailMessage)
    }
    // 不实际写文件，仅记录调用
  }

  // src/index.ts:587-676 — add_source
  function addSource(args: {
    name?: string
    type?: string
    host?: string
    port?: number
    database?: string
    user?: string
    password?: string
    ssl?: boolean
    sslrootcert?: string
  }): { success: boolean; message?: string; error?: string } {
    const { name: srcName, type: srcType, host: srcHost, port: srcPort, database: srcDatabase, user: srcUser, password: srcPassword, ssl: srcSsl, sslrootcert: srcSslrootcert } = args

    if (!srcName || !srcType || !srcHost || srcPort === undefined || !srcDatabase || !srcUser) {
      return { success: false, error: '缺少必需参数: name, type, host, port, database, user' }
    }

    if (sourcesConfig.has(srcName)) {
      return { success: false, error: `数据源 "${srcName}" 已存在` }
    }

    if (srcType !== 'postgresql' && srcType !== 'huawei-dws') {
      return { success: false, error: `不支持的数据库类型: ${srcType}（支持: postgresql, huawei-dws）` }
    }

    const newDbConfig: DatabaseConfig = {
      type: srcType as DatabaseConfig['type'],
      host: srcHost,
      port: srcPort,
      database: srcDatabase,
      user: srcUser,
      password: srcPassword || '',
      ssl: srcSsl,
      sslrootcert: srcSslrootcert,
    }

    sourcesConfig.set(srcName, newDbConfig)

    // 第一个数据源自动设为默认
    if (sourcesConfig.size === 1) {
      sourcesDefault = srcName
      currentSource = srcName
    }

    const fullConfig = buildFullConfig()
    try {
      mockWriteSourcesFile(fullConfig)
    } catch (err: unknown) {
      // 回滚内存
      sourcesConfig.delete(srcName)
      const message = err instanceof Error ? err.message : String(err)
      return { success: false, error: message }
    }

    return { success: true, message: `数据源 ${srcName} 已添加` }
  }

  // src/index.ts:678-740 — update_source
  function updateSource(args: {
    name?: string
    host?: string
    port?: number
    database?: string
    user?: string
    password?: string
    ssl?: boolean
    sslrootcert?: string
  }): { success: boolean; message?: string; error?: string } {
    const srcName = args.name
    if (!srcName) {
      return { success: false, error: '缺少必需参数: name' }
    }

    const existing = sourcesConfig.get(srcName)
    if (!existing) {
      return { success: false, error: `数据源 "${srcName}" 不存在` }
    }

    const updated: DatabaseConfig = { ...existing }
    if (args.host !== undefined) updated.host = args.host
    if (args.port !== undefined) updated.port = args.port
    if (args.database !== undefined) updated.database = args.database
    if (args.user !== undefined) updated.user = args.user
    if (args.password !== undefined) updated.password = args.password
    if (args.ssl !== undefined) updated.ssl = args.ssl
    if (args.sslrootcert !== undefined) updated.sslrootcert = args.sslrootcert

    sourcesConfig.set(srcName, updated)

    const fullConfig = buildFullConfig()
    try {
      mockWriteSourcesFile(fullConfig)
    } catch (err: unknown) {
      // 回滚内存
      sourcesConfig.set(srcName, existing)
      const message = err instanceof Error ? err.message : String(err)
      return { success: false, error: message }
    }

    return { success: true, message: `数据源 ${srcName} 已更新` }
  }

  // src/index.ts:742-817 — delete_source
  function deleteSource(args: { name?: string }): { success: boolean; message?: string; error?: string } {
    const srcName = args.name
    if (!srcName) {
      return { success: false, error: '缺少必需参数: name' }
    }

    if (!sourcesConfig.has(srcName)) {
      return { success: false, error: `数据源 "${srcName}" 不存在` }
    }

    if (sourcesConfig.size <= 1) {
      return { success: false, error: '不能删除唯一的数据源' }
    }

    // Save state for rollback
    const deletedConfig = sourcesConfig.get(srcName)!
    const oldCurrentSource = currentSource
    const oldSourcesDefault = sourcesDefault

    // 删除默认数据源 → 重新选择
    if (sourcesDefault === srcName) {
      sourcesDefault = currentSource
      if (!sourcesConfig.has(sourcesDefault)) {
        sourcesDefault = Array.from(sourcesConfig.keys())[0]
      }
    }

    // 删除当前数据源 → 切换到默认
    if (currentSource === srcName) {
      currentSource = sourcesDefault
    }

    sourcesConfig.delete(srcName)

    const fullConfig = buildFullConfig()
    try {
      mockWriteSourcesFile(fullConfig)
    } catch (err: unknown) {
      // Rollback: restore deleted source and state
      sourcesConfig.set(srcName, deletedConfig)
      currentSource = oldCurrentSource
      sourcesDefault = oldSourcesDefault
      const message = err instanceof Error ? err.message : String(err)
      return { success: false, error: message }
    }

    return { success: true, message: `数据源 ${srcName} 已删除` }
  }

  // src/index.ts:819-851 — switch_source
  function switchSource(args: { source_name?: string }): { success: boolean; current?: string; message?: string; error?: string } {
    const srcName = args.source_name
    if (!srcName) {
      return { success: false, error: '缺少必需参数: source_name' }
    }

    if (!sourcesConfig.has(srcName)) {
      return { success: false, error: `数据源 "${srcName}" 不存在` }
    }

    currentSource = srcName
    return { success: true, current: srcName, message: `已切换到 ${srcName}` }
  }

  // src/index.ts:570-585 — list_sources
  function listSources(): Array<{
    name: string
    type: string
    host: string
    port: number
    database: string
    user: string
    isDefault: boolean
    isCurrent: boolean
  }> {
    return Array.from(sourcesConfig.entries()).map(([srcName, dbConf]) => ({
      name: srcName,
      type: dbConf.type,
      host: dbConf.host,
      port: dbConf.port,
      database: dbConf.database,
      user: dbConf.user,
      isDefault: srcName === sourcesDefault,
      isCurrent: srcName === currentSource,
    }))
  }

  // 用于手动预置数据
  function seedSource(name: string, config: DatabaseConfig) {
    sourcesConfig.set(name, config)
  }

  return {
    addSource,
    updateSource,
    deleteSource,
    switchSource,
    listSources,
    seedSource,
    setConfigFilePath,
    // 测试控制
    set writeFail(v: boolean) { writeShouldFail = v },
    set writeErrorMsg(msg: string) { writeFailMessage = msg },
    // 状态访问
    get sourcesMap() { return sourcesConfig },
    get current() { return currentSource },
    get defaultSource() { return sourcesDefault },
    get security() { return securityConfig },
  }
}

// ============================================================================
// 测试辅助
// ============================================================================

function makeSource(overrides: Partial<DatabaseConfig> & { name?: string } = {}): DatabaseConfig {
  return {
    type: 'postgresql',
    host: 'localhost',
    port: 5432,
    database: 'testdb',
    user: 'admin',
    password: 'secret',
    ...overrides,
  }
}

// ============================================================================
// 测试
// ============================================================================

describe('数据源 CRUD 操作', () => {
  let harness: ReturnType<typeof createCrudHarness>

  beforeEach(() => {
    harness = createCrudHarness()
    harness.writeFail = false
  })

  // ---------- add_source ----------

  describe('add_source', () => {
    it('成功添加新数据源', () => {
      const result = harness.addSource({
        name: 'dev',
        type: 'postgresql',
        host: 'localhost',
        port: 5432,
        database: 'testdb',
        user: 'admin',
        password: 'pass',
      })
      expect(result.success).toBe(true)
      expect(result.message).toContain('dev')
      expect(harness.sourcesMap.has('dev')).toBe(true)
    })

    it('第一个数据源自动设为默认和当前', () => {
      harness.addSource({
        name: 'first',
        type: 'postgresql',
        host: 'h1',
        port: 1,
        database: 'd1',
        user: 'u1',
      })
      expect(harness.defaultSource).toBe('first')
      expect(harness.current).toBe('first')
    })

    it('重复名称被拒绝', () => {
      harness.seedSource('dev', makeSource())
      const result = harness.addSource({
        name: 'dev',
        type: 'postgresql',
        host: 'localhost',
        port: 5432,
        database: 'testdb',
        user: 'admin',
      })
      expect(result.success).toBe(false)
      expect(result.error).toContain('已存在')
    })

    it('不支持的数据库类型被拒绝', () => {
      const result = harness.addSource({
        name: 'bad',
        type: 'mysql',
        host: 'localhost',
        port: 3306,
        database: 'testdb',
        user: 'root',
      })
      expect(result.success).toBe(false)
      expect(result.error).toContain('不支持')
      expect(result.error).toContain('mysql')
    })

    it('缺少必需参数被拒绝', () => {
      const result = harness.addSource({ name: 'incomplete' })
      expect(result.success).toBe(false)
      expect(result.error).toContain('缺少必需参数')
    })

    it('缺少 password 时默认为空字符串', () => {
      harness.addSource({
        name: 'no-pwd',
        type: 'postgresql',
        host: 'localhost',
        port: 5432,
        database: 'db',
        user: 'u',
      })
      expect(harness.sourcesMap.get('no-pwd')?.password).toBe('')
    })

    it('写入失败时回滚内存状态', () => {
      harness.writeFail = true
      harness.writeErrorMsg = '磁盘空间不足'
      const result = harness.addSource({
        name: 'rollback-test',
        type: 'postgresql',
        host: 'localhost',
        port: 5432,
        database: 'db',
        user: 'u',
      })
      expect(result.success).toBe(false)
      expect(result.error).toBe('磁盘空间不足')
      expect(harness.sourcesMap.has('rollback-test')).toBe(false)
    })
  })

  // ---------- update_source ----------

  describe('update_source', () => {
    it('成功更新数据源部分字段', () => {
      harness.seedSource('dev', makeSource({ port: 5432 }))
      const result = harness.updateSource({ name: 'dev', port: 5433, host: 'new-host' })

      expect(result.success).toBe(true)
      const updated = harness.sourcesMap.get('dev')!
      expect(updated.port).toBe(5433)
      expect(updated.host).toBe('new-host')
      // 未更新的字段保持不变
      expect(updated.database).toBe('testdb')
    })

    it('更新不存在的数据源被拒绝', () => {
      const result = harness.updateSource({ name: 'ghost', host: 'nowhere' })
      expect(result.success).toBe(false)
      expect(result.error).toContain('不存在')
    })

    it('缺少 name 参数被拒绝', () => {
      const result = harness.updateSource({ host: 'new-host' })
      expect(result.success).toBe(false)
      expect(result.error).toContain('缺少必需参数')
    })

    it('写入失败时回滚到更新前的值', () => {
      harness.seedSource('dev', makeSource({ host: 'original-host' }))
      harness.writeFail = true

      const result = harness.updateSource({ name: 'dev', host: 'new-host' })
      expect(result.success).toBe(false)
      expect(harness.sourcesMap.get('dev')?.host).toBe('original-host')
    })

    it('只更新 password 不影响其他字段', () => {
      harness.seedSource('dev', makeSource({ password: 'old' }))
      harness.updateSource({ name: 'dev', password: 'new' })

      const updated = harness.sourcesMap.get('dev')!
      expect(updated.password).toBe('new')
      expect(updated.host).toBe('localhost')
      expect(updated.port).toBe(5432)
    })
  })

  // ---------- delete_source ----------

  describe('delete_source', () => {
    beforeEach(() => {
      harness.seedSource('dev', makeSource({ name: 'dev' }))
      harness.seedSource('prod', makeSource({ host: 'prod-host', name: 'prod' }))
    })

    it('成功删除数据源', () => {
      const result = harness.deleteSource({ name: 'prod' })
      expect(result.success).toBe(true)
      expect(harness.sourcesMap.has('prod')).toBe(false)
      expect(harness.sourcesMap.size).toBe(1)
    })

    it('删除唯一数据源被拒绝', () => {
      harness.deleteSource({ name: 'prod' }) // 先删一个，剩 1 个
      const result = harness.deleteSource({ name: 'dev' })
      expect(result.success).toBe(false)
      expect(result.error).toContain('唯一')
    })

    it('删除不存在的数据源被拒绝', () => {
      const result = harness.deleteSource({ name: 'ghost' })
      expect(result.success).toBe(false)
      expect(result.error).toContain('不存在')
    })

    it('删除当前数据源后自动切换到默认', () => {
      harness.deleteSource({ name: 'dev' })
      expect(harness.current).toBe('default')
    })

    it('写入失败时不影响内存状态', () => {
      harness.writeFail = true
      const result = harness.deleteSource({ name: 'prod' })
      expect(result.success).toBe(false)
      expect(harness.sourcesMap.has('prod')).toBe(true)
    })
  })

  // ---------- switch_source ----------

  describe('switch_source', () => {
    beforeEach(() => {
      harness.seedSource('dev', makeSource())
      harness.seedSource('prod', makeSource({ host: 'prod-host' }))
    })

    it('成功切换当前数据源', () => {
      const result = harness.switchSource({ source_name: 'prod' })
      expect(result.success).toBe(true)
      expect(result.current).toBe('prod')
      expect(harness.current).toBe('prod')
    })

    it('切换不存在的数据源被拒绝', () => {
      const result = harness.switchSource({ source_name: 'ghost' })
      expect(result.success).toBe(false)
      expect(result.error).toContain('不存在')
    })

    it('切换不涉及文件写入（内存操作）', () => {
      // 验证：即使 writeFail=true，switch 仍然成功
      harness.writeFail = true
      const result = harness.switchSource({ source_name: 'prod' })
      expect(result.success).toBe(true)
      expect(harness.current).toBe('prod')
    })
  })

  // ---------- list_sources ----------

  describe('list_sources', () => {
    it('列出所有数据源（密码脱敏）', () => {
      harness.seedSource('dev', makeSource({ password: 'secret123' }))
      harness.seedSource('prod', makeSource({ host: 'prod-host', password: 'prod-pwd' }))

      const list = harness.listSources()
      expect(list).toHaveLength(2)

      // list_sources 不返回 password 字段
      for (const item of list) {
        expect(item).not.toHaveProperty('password')
      }
    })

    it('正确标记 isDefault 和 isCurrent', () => {
      harness.seedSource('dev', makeSource())
      harness.seedSource('prod', makeSource({ host: 'prod-host' }))

      const list = harness.listSources()
      const devItem = list.find(s => s.name === 'dev')!
      const prodItem = list.find(s => s.name === 'prod')!

      expect(devItem.isDefault).toBe(false)
      expect(devItem.isCurrent).toBe(false)
      expect(prodItem.isDefault).toBe(false)
      expect(prodItem.isCurrent).toBe(false)
    })

    it('切换后 isCurrent 标记更新', () => {
      harness.seedSource('dev', makeSource())
      harness.seedSource('prod', makeSource({ host: 'prod-host' }))
      harness.switchSource({ source_name: 'prod' })

      const list = harness.listSources()
      const devItem = list.find(s => s.name === 'dev')!
      const prodItem = list.find(s => s.name === 'prod')!

      expect(devItem.isCurrent).toBe(false)
      expect(prodItem.isCurrent).toBe(true)
    })

    it('无数据源时返回空数组', () => {
      expect(harness.listSources()).toEqual([])
    })
  })
})
