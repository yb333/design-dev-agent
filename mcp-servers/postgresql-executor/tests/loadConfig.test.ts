/**
 * loadConfig.test.ts — 配置加载逻辑测试
 *
 * 源文件 src/index.ts 不导出内部函数，以下逻辑从源码提取用于测试。
 * Extracted from src/index.ts lines 81-205.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import * as path from 'path'
import * as fs from 'fs'

const { mockReadFileSync, mockExistsSync, mockWriteFileSync } = vi.hoisted(() => ({
  mockReadFileSync: vi.fn(),
  mockExistsSync: vi.fn(),
  mockWriteFileSync: vi.fn(),
}))

vi.mock('fs', () => ({
  readFileSync: mockReadFileSync,
  existsSync: mockExistsSync,
  writeFileSync: mockWriteFileSync,
  default: {
    readFileSync: mockReadFileSync,
    existsSync: mockExistsSync,
    writeFileSync: mockWriteFileSync,
  },
}))

// ============================================================================
// 从 src/index.ts 提取的纯逻辑函数（用于测试）
// ============================================================================

// src/index.ts:81-83 — 配置目录
function getConfigDir(): string {
  return path.dirname(process.env.DB_CONFIG || path.join(__dirname, '..', 'db-sources.json'))
}

// src/index.ts:85-87 — 多数据源配置路径
function getSourcesFilePath(): string {
  return process.env.DB_CONFIG || path.join(__dirname, '..', 'db-sources.json')
}

// src/index.ts:89-91 — 旧版配置路径
function getLegacyConfigPath(): string {
  return path.join(getConfigDir(), 'db-config.json')
}

// src/index.ts:97-104 — 密码环境变量解析
function resolvePassword(password: string): string {
  const envRefMatch = password.match(/^\$\{([^}]+)\}$/)
  if (envRefMatch) {
    const envValue = process.env[envRefMatch[1]]
    return envValue !== undefined ? envValue : password
  }
  return password
}

// src/index.ts:110-124 — 读取多数据源配置
function readSourcesFile(configFilePath: string): {
  default: string
  sources: Record<string, unknown>
  security: { allowWriteOperations: boolean; maxRows: number; timeout: number }
} {
  const raw = fs.readFileSync(configFilePath, 'utf-8')
  const config = JSON.parse(raw)
  if (!config.sources || typeof config.sources !== 'object') {
    throw new Error('配置文件格式错误: 缺少 sources 字段')
  }
  if (!config.security) {
    throw new Error('配置文件格式错误: 缺少 security 字段')
  }
  return config
}

// src/index.ts:126-134 — 写入多数据源配置
function writeSourcesFile(filePath: string, config: unknown): void {
  try {
    fs.writeFileSync(filePath, JSON.stringify(config, null, 2), 'utf-8')
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err)
    throw new Error(`写入配置文件失败: ${message}`)
  }
}

// src/index.ts:140-205 — 配置加载（兼容旧格式），依赖 sourcesConfig / currentSource / securityConfig 状态
// 这里用闭包模拟模块级状态，返回受控的 loadConfig
function createLoadConfigHarness() {
  const sourcesConfig = new Map<string, unknown>()
  let currentSource = 'default'
  let securityConfig = { allowWriteOperations: false, maxRows: 100, timeout: 0 }
  let sourcesDefault = 'default'
  let configFilePath = ''

  function harnessLoadConfig(): {
    database: unknown
    security: unknown
  } {
    const sourcesPath = getSourcesFilePath()
    const legacyPath = getLegacyConfigPath()

    if (sourcesConfig.size > 0) {
      const activeConfig = sourcesConfig.get(currentSource)
      if (activeConfig) {
        return {
          database: { ...activeConfig, password: resolvePassword((activeConfig as { password: string }).password || '') },
          security: securityConfig,
        }
      }
    }

    if (fs.existsSync(sourcesPath)) {
      try {
        const config = readSourcesFile(sourcesPath)
        sourcesDefault = config.default || Object.keys(config.sources)[0]
        currentSource = sourcesDefault

        for (const [name, dbConf] of Object.entries(config.sources)) {
          sourcesConfig.set(name, dbConf)
        }

        securityConfig = config.security
        const activeConfig = sourcesConfig.get(currentSource)!
        return {
          database: { ...activeConfig, password: resolvePassword((activeConfig as { password: string }).password || '') },
          security: securityConfig,
        }
      } catch {
        // fall through to legacy
      }
    }

    if (fs.existsSync(legacyPath)) {
      try {
        const raw = fs.readFileSync(legacyPath, 'utf-8')
        const config = JSON.parse(raw)
        if (!config.database || !config.security) {
          throw new Error('旧配置文件格式错误')
        }

        sourcesConfig.set('default', config.database)
        sourcesDefault = 'default'
        currentSource = 'default'
        securityConfig = config.security

        return {
          database: { ...config.database, password: resolvePassword(config.database.password || '') },
          security: config.security,
        }
      } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err)
        throw new Error(`配置加载失败: ${message}`)
      }
    }

    throw new Error(
      `配置文件不存在: ${sourcesPath}\n请创建 db-sources.json 或 db-config.json 配置文件`
    )
  }

  // 暴露内部状态以便断言
  return {
    loadConfig: harnessLoadConfig,
    get sourcesMap() { return sourcesConfig },
    get current() { return currentSource },
    get defaultSource() { return sourcesDefault },
    get security() { return securityConfig },
    get configPath() { return configFilePath },
  }
}

// ============================================================================
// 测试
// ============================================================================

describe('loadConfig 配置加载', () => {
  let originalDbConfig: string | undefined

  beforeEach(() => {
    originalDbConfig = process.env.DB_CONFIG
    delete process.env.DB_CONFIG
    vi.unstubAllEnvs()
    mockReadFileSync.mockClear()
    mockExistsSync.mockClear()
    mockWriteFileSync.mockClear()
  })

  afterEach(() => {
    if (originalDbConfig !== undefined) {
      process.env.DB_CONFIG = originalDbConfig
    } else {
      delete process.env.DB_CONFIG
    }
    vi.restoreAllMocks()
  })

  // ---------- resolvePassword ----------

  describe('resolvePassword', () => {
    it('解析 ${ENV_VAR} 格式并返回环境变量值', () => {
      process.env.MY_SECRET = 'actual_password'
      expect(resolvePassword('${MY_SECRET}')).toBe('actual_password')
      delete process.env.MY_SECRET
    })

    it('环境变量不存在时返回原始字符串', () => {
      delete process.env.NONEXISTENT_VAR
      expect(resolvePassword('${NONEXISTENT_VAR}')).toBe('${NONEXISTENT_VAR}')
    })

    it('非 ${...} 格式直接返回原字符串', () => {
      expect(resolvePassword('plain_password')).toBe('plain_password')
    })

    it('部分匹配 ${...} 格式不解析', () => {
      expect(resolvePassword('prefix_${VAR}_suffix')).toBe('prefix_${VAR}_suffix')
    })

    it('空字符串直接返回', () => {
      expect(resolvePassword('')).toBe('')
    })
  })

  // ---------- 配置路径 ----------

  describe('配置路径解析', () => {
    it('DB_CONFIG 未设置时 getSourcesFilePath 返回默认路径', () => {
      const result = getSourcesFilePath()
      expect(result).toContain('db-sources.json')
      expect(result).not.toContain('custom')
    })

    it('DB_CONFIG 已设置时 getSourcesFilePath 返回自定义路径', () => {
      process.env.DB_CONFIG = '/custom/path/db-sources.json'
      expect(getSourcesFilePath()).toBe('/custom/path/db-sources.json')
    })

    it('getConfigDir 返回配置文件所在目录', () => {
      process.env.DB_CONFIG = '/etc/myapp/db-sources.json'
      expect(getConfigDir()).toBe('/etc/myapp')
    })

    it('getLegacyConfigPath 基于配置目录生成旧版路径', () => {
      process.env.DB_CONFIG = '/data/config/db-sources.json'
      expect(getLegacyConfigPath()).toBe('/data/config/db-config.json')
    })

    it('DB_CONFIG 未设置时 getLegacyConfigPath 使用相对路径', () => {
      const result = getLegacyConfigPath()
      expect(result).toContain('db-config.json')
      expect(result).not.toContain('custom')
    })
  })

  // ---------- readSourcesFile ----------

  describe('readSourcesFile', () => {
    it('正常解析合法的 JSON 配置文件', () => {
      const validConfig = {
        default: 'dev',
        sources: { dev: { host: 'localhost', port: 5432 } },
        security: { allowWriteOperations: false, maxRows: 100, timeout: 0 },
      }
      mockReadFileSync.mockReturnValue(JSON.stringify(validConfig))
      const result = readSourcesFile('/fake/path.json')
      expect(result.default).toBe('dev')
      expect(result.sources.dev).toEqual({ host: 'localhost', port: 5432 })
      expect(result.security.maxRows).toBe(100)
    })

    it('缺少 sources 字段时抛出错误', () => {
      mockReadFileSync.mockReturnValue(JSON.stringify({ security: {} }))
      expect(() => readSourcesFile('/fake/path.json')).toThrow('缺少 sources 字段')
    })

    it('缺少 security 字段时抛出错误', () => {
      mockReadFileSync.mockReturnValue(JSON.stringify({ sources: {} }))
      expect(() => readSourcesFile('/fake/path.json')).toThrow('缺少 security 字段')
    })
  })

  // ---------- loadConfig（含状态） ----------

  describe('loadConfig 多数据源路径', () => {
    it('从 db-sources.json 加载多数据源配置', () => {
      const multiConfig = {
        default: 'dev',
        sources: {
          dev: { type: 'postgresql', host: 'localhost', port: 5432, database: 'testdb', user: 'admin', password: 'pass' },
          prod: { type: 'huawei-dws', host: '10.0.0.1', port: 8000, database: 'proddb', user: 'etl', password: '${DWS_PWD}' },
        },
        security: { allowWriteOperations: false, maxRows: 50, timeout: 30000 },
      }
      mockExistsSync.mockReturnValue(true)
      mockReadFileSync.mockReturnValue(JSON.stringify(multiConfig))

      const harness = createLoadConfigHarness()
      const result = harness.loadConfig()

      expect(harness.sourcesMap.size).toBe(2)
      expect(harness.current).toBe('dev')
      expect((result.database as Record<string, unknown>).password).toBe('pass')
      expect((result.security as Record<string, unknown>).maxRows).toBe(50)
    })

    it('多数据源配置中解析 ${ENV_VAR} 密码', () => {
      process.env.DWS_PWD = 'resolved_secret'
      const multiConfig = {
        default: 'prod',
        sources: {
          prod: { type: 'huawei-dws', host: '10.0.0.1', port: 8000, database: 'proddb', user: 'etl', password: '${DWS_PWD}' },
        },
        security: { allowWriteOperations: true, maxRows: 200, timeout: 0 },
      }
      mockExistsSync.mockReturnValue(true)
      mockReadFileSync.mockReturnValue(JSON.stringify(multiConfig))

      const harness = createLoadConfigHarness()
      const result = harness.loadConfig()

      expect((result.database as Record<string, unknown>).password).toBe('resolved_secret')
      delete process.env.DWS_PWD
    })

    it('内存中已有配置时直接返回不重新加载', () => {
      const harness = createLoadConfigHarness()
      // 手动向 sourcesConfig 注入数据（使用 default 作为 key 以匹配 currentSource）
      harness.sourcesMap.set('default', { type: 'postgresql', host: 'cached-host', port: 5432, database: 'cached_db', user: 'u', password: 'p' })

      // fs mock 不应被调用
      mockExistsSync.mockClear()
      mockExistsSync.mockReturnValue(false)

      const result = harness.loadConfig()
      expect(mockExistsSync).not.toHaveBeenCalled()
      expect((result.database as Record<string, unknown>).host).toBe('cached-host')
    })
  })

  describe('loadConfig 旧版回退', () => {
    it('db-sources.json 不存在时回退读取 db-config.json', () => {
      const legacyConfig = {
        database: { type: 'postgresql', host: 'legacy-host', port: 5433, database: 'legacy_db', user: 'legacy', password: 'old' },
        security: { allowWriteOperations: false, maxRows: 100, timeout: 0 },
      }

      mockExistsSync.mockImplementation((p: string) => {
        // db-sources.json → false, db-config.json → true
        return String(p).endsWith('db-config.json')
      })

      mockReadFileSync.mockReturnValue(JSON.stringify(legacyConfig))

      const harness = createLoadConfigHarness()
      const result = harness.loadConfig()

      expect(harness.sourcesMap.size).toBe(1)
      expect(harness.sourcesMap.has('default')).toBe(true)
      expect(harness.current).toBe('default')
      expect((result.database as Record<string, unknown>).host).toBe('legacy-host')
    })

    it('两个配置文件都不存在时抛出错误', () => {
      mockExistsSync.mockReturnValue(false)

      const harness = createLoadConfigHarness()
      expect(() => harness.loadConfig()).toThrow('配置文件不存在')
    })

    it('旧版配置缺少 database 字段时抛出错误', () => {
      mockExistsSync.mockImplementation((p: string) => String(p).endsWith('db-config.json'))
      mockReadFileSync.mockReturnValue(JSON.stringify({ security: {} }))

      const harness = createLoadConfigHarness()
      expect(() => harness.loadConfig()).toThrow('配置加载失败')
    })
  })

  // ---------- writeSourcesFile ----------

  describe('writeSourcesFile', () => {
    it('成功写入 JSON 配置文件', () => {
      mockWriteFileSync.mockImplementation(() => {})
      const data = { default: 'dev', sources: {}, security: {} }

      expect(() => writeSourcesFile('/fake/out.json', data)).not.toThrow()
      expect(mockWriteFileSync).toHaveBeenCalledWith('/fake/out.json', JSON.stringify(data, null, 2), 'utf-8')
    })

    it('写入失败时抛出带原始错误信息的异常', () => {
      mockWriteFileSync.mockImplementation(() => {
        throw new Error('EACCES: permission denied')
      })

      expect(() => writeSourcesFile('/readonly/path.json', {})).toThrow('写入配置文件失败: EACCES: permission denied')
    })

    it('写入非 Error 类型异常时转换为字符串', () => {
      mockWriteFileSync.mockImplementation(() => {
        throw 'string_error'
      })

      expect(() => writeSourcesFile('/fake/path.json', {})).toThrow('写入配置文件失败: string_error')
    })
  })
})
