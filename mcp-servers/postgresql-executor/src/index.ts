#!/usr/bin/env node
/**
 * PostgreSQL / Huawei Cloud DWS MCP Server
 *
 * 功能：支持多数据源管理 + SQL 执行
 * 兼容：若 db-sources.json 不存在，自动回退读取 db-config.json 作为单数据源
 */

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  ErrorCode,
  McpError,
} from '@modelcontextprotocol/sdk/types.js';
import { Client } from 'pg';
import * as fs from 'fs';
import * as path from 'path';

// ============================================================================
// 类型定义
// ============================================================================

interface DatabaseConfig {
  type: 'postgresql' | 'huawei-dws';
  host: string;
  port: number;
  database: string;
  user: string;
  password: string;
  ssl?: boolean;
  sslcert?: string;
  sslkey?: string;
  sslrootcert?: string;
}

interface SecurityConfig {
  allowWriteOperations: boolean;
  maxRows: number;
  timeout: number;
}

/** Legacy single-source config (db-config.json) */
interface LegacyConfig {
  database: DatabaseConfig;
  security: SecurityConfig;
}

/** Multi-source config (db-sources.json) */
interface SourcesConfig {
  default: string;
  sources: Record<string, DatabaseConfig>;
  security: SecurityConfig;
}

/** Runtime config returned to existing SQL tools */
interface Config {
  database: DatabaseConfig;
  security: SecurityConfig;
}

// ============================================================================
// 多数据源内存状态
// ============================================================================

const sourcesConfig = new Map<string, DatabaseConfig>();
let currentSource = 'default';
let securityConfig: SecurityConfig = {
  allowWriteOperations: false,
  maxRows: 100,
  timeout: 0,
};
let sourcesDefault = 'default';
let configFilePath = '';

// ============================================================================
// 配置文件路径
// ============================================================================

function getConfigDir(): string {
  return path.dirname(process.env.DB_CONFIG || path.join(__dirname, '..', 'db-sources.json'));
}

function getSourcesFilePath(): string {
  return process.env.DB_CONFIG || path.join(__dirname, '..', 'db-sources.json');
}

function getLegacyConfigPath(): string {
  return path.join(getConfigDir(), 'db-config.json');
}

// ============================================================================
// 密码环境变量解析
// ============================================================================

function resolvePassword(password: string): string {
  const envRefMatch = password.match(/^\$\{([^}]+)\}$/);
  if (envRefMatch) {
    const envValue = process.env[envRefMatch[1]];
    return envValue !== undefined ? envValue : password;
  }
  return password;
}

// ============================================================================
// 配置文件读写
// ============================================================================

function readSourcesFile(): SourcesConfig {
  configFilePath = getSourcesFilePath();
  if (!fs.existsSync(configFilePath)) {
    throw new Error(`配置文件不存在: ${configFilePath}`);
  }
  const raw = fs.readFileSync(configFilePath, 'utf-8');
  const config = JSON.parse(raw) as SourcesConfig;
  if (!config.sources || typeof config.sources !== 'object') {
    throw new Error('配置文件格式错误: 缺少 sources 字段');
  }
  if (!config.security) {
    throw new Error('配置文件格式错误: 缺少 security 字段');
  }
  return config;
}

function writeSourcesFile(config: SourcesConfig): void {
  configFilePath = configFilePath || getSourcesFilePath();
  try {
    fs.writeFileSync(configFilePath, JSON.stringify(config, null, 2), 'utf-8');
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(`写入配置文件失败: ${message}`);
  }
}

// ============================================================================
// 配置加载（兼容旧格式）
// ============================================================================

function loadConfig(): Config {
  const sourcesPath = getSourcesFilePath();
  const legacyPath = getLegacyConfigPath();

  // 如果内存中已有数据源配置，直接使用
  if (sourcesConfig.size > 0) {
    const activeConfig = sourcesConfig.get(currentSource);
    if (activeConfig) {
      return {
        database: { ...activeConfig, password: resolvePassword(activeConfig.password) },
        security: securityConfig,
      };
    }
  }

  // 首次加载：尝试多数据源配置
  if (fs.existsSync(sourcesPath)) {
    try {
      const config = readSourcesFile();
      sourcesDefault = config.default || Object.keys(config.sources)[0];
      currentSource = sourcesDefault;

      for (const [name, dbConf] of Object.entries(config.sources)) {
        sourcesConfig.set(name, dbConf);
      }

      securityConfig = config.security;
      const activeConfig = sourcesConfig.get(currentSource)!;
      return {
        database: { ...activeConfig, password: resolvePassword(activeConfig.password) },
        security: securityConfig,
      };
    } catch {
      // 解析失败，fall through to legacy
    }
  }

  // 回退：读取旧格式 db-config.json
  if (fs.existsSync(legacyPath)) {
    try {
      const raw = fs.readFileSync(legacyPath, 'utf-8');
      const config = JSON.parse(raw) as LegacyConfig;
      if (!config.database || !config.security) {
        throw new Error('旧配置文件格式错误');
      }

      // 作为单数据源 "default" 导入
      sourcesConfig.set('default', config.database);
      sourcesDefault = 'default';
      currentSource = 'default';
      securityConfig = config.security;

      return {
        database: { ...config.database, password: resolvePassword(config.database.password) },
        security: config.security,
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      throw new Error(`配置加载失败: ${message}`);
    }
  }

  throw new Error(
    `配置文件不存在: ${sourcesPath}\n请创建 db-sources.json 或 db-config.json 配置文件`
  );
}

// ============================================================================
// 数据库连接
// ============================================================================

async function createClient(config: DatabaseConfig): Promise<Client> {
  const resolvedConfig = { ...config, password: resolvePassword(config.password) };

  let sslConfig: false | object = false;
  if (resolvedConfig.ssl) {
    try {
      sslConfig = {
        cert: resolvedConfig.sslcert ? fs.readFileSync(resolvedConfig.sslcert) : undefined,
        key: resolvedConfig.sslkey ? fs.readFileSync(resolvedConfig.sslkey) : undefined,
        ca: resolvedConfig.sslrootcert ? fs.readFileSync(resolvedConfig.sslrootcert) : undefined,
        // 有 CA 证书时严格验证，无 CA 时宽松验证（华为云 DWS 证书可能不在 Node.js 内置 CA 中）
        rejectUnauthorized: !!resolvedConfig.sslrootcert,
      };
    } catch (err) {
      throw new Error(`SSL 证书读取失败: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  const client = new Client({
    host: resolvedConfig.host,
    port: resolvedConfig.port || 5432,
    database: resolvedConfig.database,
    user: resolvedConfig.user,
    password: resolvedConfig.password,
    ssl: sslConfig,
    connectionTimeoutMillis: 15000,
  });

  // 防止异步错误导致进程崩溃（Windows 上 TLS 握手失败可能触发未捕获异常）
  client.on('error', (err) => {
    console.error('pg client error:', err.message);
  });

  await client.connect();
  return client;
}

// ============================================================================
// SQL 执行
// ============================================================================

interface ExecuteResult {
  success: boolean;
  rows?: Record<string, unknown>[];
  rowCount?: number;
  columns?: string[];
  executionTime?: string;
  error?: string;
}

interface PgField {
  name: string;
}

async function executeSql(sql: string, config: Config): Promise<ExecuteResult> {
  const startTime = Date.now();
  let client: Client | null = null;

  try {
    if (!config.security.allowWriteOperations) {
      const writeKeywords = [
        'INSERT',
        'UPDATE',
        'DELETE',
        'DROP',
        'CREATE',
        'ALTER',
        'TRUNCATE',
        'GRANT',
        'REVOKE',
      ];
      const upperSql = sql.toUpperCase().trim();
      for (const keyword of writeKeywords) {
        if (upperSql.startsWith(keyword)) {
          return {
            success: false,
            error: `写操作已被禁用（${keyword}）。如需启用，请在配置中设置 allowWriteOperations: true`,
          };
        }
      }
    }

    client = await createClient(config.database);

    // timeout: 0 = 不限制，由数据库 statement_timeout 控制
    // timeout > 0 = 使用 pg 库原生查询超时（内部自动发送 CANCEL）
    const queryOptions = config.security.timeout > 0
      ? { text: sql, timeout: config.security.timeout }
      : sql;
    const result = await client.query(queryOptions);

    const executionTime = `${Date.now() - startTime}ms`;

    if (result.rows) {
      const limitedRows = result.rows.slice(0, config.security.maxRows);
      const columns = result.fields?.map((f: PgField) => f.name) || [];

      return {
        success: true,
        rows: limitedRows,
        rowCount: result.rowCount || result.rows.length,
        columns,
        executionTime,
      };
    } else {
      return {
        success: true,
        rowCount: result.rowCount || 0,
        executionTime,
      };
    }
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : '未知错误';
    return {
      success: false,
      error: message,
      executionTime: `${Date.now() - startTime}ms`,
    };
  } finally {
    if (client) {
      await client.end();
    }
  }
}

// ============================================================================
// 辅助：确保多数据源配置已初始化
// ============================================================================

function ensureSourcesInitialized(): void {
  if (sourcesConfig.size === 0) {
    loadConfig();
  }
}

// ============================================================================
// MCP Server 定义
// ============================================================================

const server = new Server(
  {
    name: 'postgresql-executor',
    version: '1.0.0',
  },
  {
    capabilities: {
      tools: {},
    },
  }
);

// ============================================================================
// 工具列表（3 existing + 6 new）
// ============================================================================

server.setRequestHandler(ListToolsRequestSchema, async () => {
  return {
    tools: [
      // --- 现有 SQL 工具 ---
      {
        name: 'execute_sql',
        description: '在 PostgreSQL / 华为云 DWS 数据库中执行 SQL 语句，返回结果',
        inputSchema: {
          type: 'object',
          properties: {
            sql: {
              type: 'string',
              description: '要执行的 SQL 语句（默认只允许 SELECT）',
            },
          },
          required: ['sql'],
        },
      },
      {
        name: 'list_tables',
        description: '列出数据库中的所有表',
        inputSchema: {
          type: 'object',
          properties: {},
        },
      },
      {
        name: 'describe_table',
        description: '查看表的结构（字段名、类型等）',
        inputSchema: {
          type: 'object',
          properties: {
            table_name: {
              type: 'string',
              description: '表名',
            },
          },
          required: ['table_name'],
        },
      },
      // --- 数据源管理工具 ---
      {
        name: 'list_sources',
        description: '列出所有已配置的数据源',
        inputSchema: {
          type: 'object',
          properties: {},
        },
      },
      {
        name: 'add_source',
        description: '添加新的数据源',
        inputSchema: {
          type: 'object',
          properties: {
            name: { type: 'string', description: '数据源名称（唯一标识）' },
            type: { type: 'string', description: '数据库类型: postgresql 或 huawei-dws' },
            host: { type: 'string', description: '数据库主机地址' },
            port: { type: 'number', description: '端口号' },
            database: { type: 'string', description: '数据库名' },
            user: { type: 'string', description: '用户名' },
            password: { type: 'string', description: '密码（支持 ${ENV_VAR} 格式引用环境变量）' },
            ssl: { type: 'boolean', description: '是否启用 SSL' },
            sslrootcert: { type: 'string', description: 'CA 证书路径' },
          },
          required: ['name', 'type', 'host', 'port', 'database', 'user'],
        },
      },
      {
        name: 'update_source',
        description: '更新已有数据源的配置（部分更新）',
        inputSchema: {
          type: 'object',
          properties: {
            name: { type: 'string', description: '要更新的数据源名称' },
            host: { type: 'string', description: '数据库主机地址' },
            port: { type: 'number', description: '端口号' },
            database: { type: 'string', description: '数据库名' },
            user: { type: 'string', description: '用户名' },
            password: { type: 'string', description: '密码（支持 ${ENV_VAR} 格式引用环境变量）' },
            ssl: { type: 'boolean', description: '是否启用 SSL' },
            sslrootcert: { type: 'string', description: 'CA 证书路径' },
          },
          required: ['name'],
        },
      },
      {
        name: 'delete_source',
        description: '删除数据源',
        inputSchema: {
          type: 'object',
          properties: {
            name: { type: 'string', description: '要删除的数据源名称' },
          },
          required: ['name'],
        },
      },
      {
        name: 'switch_source',
        description: '切换当前活动的数据源',
        inputSchema: {
          type: 'object',
          properties: {
            source_name: { type: 'string', description: '要切换到的数据源名称' },
          },
          required: ['source_name'],
        },
      },
      {
        name: 'test_connection',
        description: '测试数据源连接是否正常',
        inputSchema: {
          type: 'object',
          properties: {
            source_name: { type: 'string', description: '要测试的数据源名称（可选，默认测试当前数据源）' },
          },
        },
      },
    ],
  };
});

// ============================================================================
// 工具调用路由
// ============================================================================

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;

  // ---------- 现有 SQL 工具（无变更） ----------

  if (name === 'execute_sql') {
    let config: Config;
    try {
      config = loadConfig();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      throw new McpError(ErrorCode.InternalError, `配置加载失败: ${message}`);
    }

    const sql = args?.sql as string | undefined;
    if (!sql) {
      throw new McpError(ErrorCode.InvalidParams, '缺少 sql 参数');
    }

    const result = await executeSql(sql, config);
    return {
      content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }],
    };
  }

  if (name === 'list_tables') {
    let config: Config;
    try {
      config = loadConfig();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      throw new McpError(ErrorCode.InternalError, `配置加载失败: ${message}`);
    }

    const sql = `
      SELECT table_name, table_type
      FROM information_schema.tables
      WHERE table_schema = 'public'
      ORDER BY table_name
    `;
    const result = await executeSql(sql, config);
    return {
      content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }],
    };
  }

  if (name === 'describe_table') {
    let config: Config;
    try {
      config = loadConfig();
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      throw new McpError(ErrorCode.InternalError, `配置加载失败: ${message}`);
    }

    const tableName = args?.table_name as string | undefined;
    if (!tableName) {
      throw new McpError(ErrorCode.InvalidParams, '缺少 table_name 参数');
    }

    const sql = `
      SELECT
        column_name,
        data_type,
        is_nullable,
        column_default
      FROM information_schema.columns
      WHERE table_name = '${tableName}'
      ORDER BY ordinal_position
    `;
    const result = await executeSql(sql, config);
    return {
      content: [{ type: 'text' as const, text: JSON.stringify(result, null, 2) }],
    };
  }

  // ---------- 数据源管理工具 ----------

  if (name === 'list_sources') {
    ensureSourcesInitialized();
    const sourceList = Array.from(sourcesConfig.entries()).map(([srcName, dbConf]) => ({
      name: srcName,
      type: dbConf.type,
      host: dbConf.host,
      port: dbConf.port,
      database: dbConf.database,
      user: dbConf.user,
      isDefault: srcName === sourcesDefault,
      isCurrent: srcName === currentSource,
    }));
    return {
      content: [{ type: 'text' as const, text: JSON.stringify(sourceList, null, 2) }],
    };
  }

  if (name === 'add_source') {
    const srcName = args?.name as string | undefined;
    const srcType = args?.type as string | undefined;
    const srcHost = args?.host as string | undefined;
    const srcPort = args?.port as number | undefined;
    const srcDatabase = args?.database as string | undefined;
    const srcUser = args?.user as string | undefined;
    const srcPassword = args?.password as string | undefined;
    const srcSsl = args?.ssl as boolean | undefined;
    const srcSslrootcert = args?.sslrootcert as string | undefined;

    if (!srcName || !srcType || !srcHost || srcPort === undefined || !srcDatabase || !srcUser) {
      throw new McpError(ErrorCode.InvalidParams, '缺少必需参数: name, type, host, port, database, user');
    }

    ensureSourcesInitialized();

    if (sourcesConfig.has(srcName)) {
      return {
        content: [
          {
            type: 'text' as const,
            text: JSON.stringify({ success: false, error: `数据源 "${srcName}" 已存在` }, null, 2),
          },
        ],
      };
    }

    if (srcType !== 'postgresql' && srcType !== 'huawei-dws') {
      return {
        content: [
          {
            type: 'text' as const,
            text: JSON.stringify({ success: false, error: `不支持的数据库类型: ${srcType}（支持: postgresql, huawei-dws）` }, null, 2),
          },
        ],
      };
    }

    const newDbConfig: DatabaseConfig = {
      type: srcType,
      host: srcHost,
      port: srcPort,
      database: srcDatabase,
      user: srcUser,
      password: srcPassword || '',
      ssl: srcSsl,
      sslrootcert: srcSslrootcert,
    };

    sourcesConfig.set(srcName, newDbConfig);

    // 如果是第一个数据源，自动设为默认
    if (sourcesConfig.size === 1) {
      sourcesDefault = srcName;
      currentSource = srcName;
    }

    // 写入文件
    const fullConfig: SourcesConfig = {
      default: sourcesDefault,
      sources: Object.fromEntries(sourcesConfig),
      security: securityConfig,
    };

    try {
      writeSourcesFile(fullConfig);
    } catch (err: unknown) {
      // 回滚内存
      sourcesConfig.delete(srcName);
      const message = err instanceof Error ? err.message : String(err);
      return {
        content: [
          {
            type: 'text' as const,
            text: JSON.stringify({ success: false, error: message }, null, 2),
          },
        ],
      };
    }

    return {
      content: [
        {
          type: 'text' as const,
          text: JSON.stringify({ success: true, message: `数据源 ${srcName} 已添加` }, null, 2),
        },
      ],
    };
  }

  if (name === 'update_source') {
    const srcName = args?.name as string | undefined;
    if (!srcName) {
      throw new McpError(ErrorCode.InvalidParams, '缺少必需参数: name');
    }

    ensureSourcesInitialized();

    const existing = sourcesConfig.get(srcName);
    if (!existing) {
      return {
        content: [
          {
            type: 'text' as const,
            text: JSON.stringify({ success: false, error: `数据源 "${srcName}" 不存在` }, null, 2),
          },
        ],
      };
    }

    // 部分更新
    const updated: DatabaseConfig = { ...existing };
    if (args?.host !== undefined) updated.host = args.host as string;
    if (args?.port !== undefined) updated.port = args.port as number;
    if (args?.database !== undefined) updated.database = args.database as string;
    if (args?.user !== undefined) updated.user = args.user as string;
    if (args?.password !== undefined) updated.password = args.password as string;
    if (args?.ssl !== undefined) updated.ssl = args.ssl as boolean;
    if (args?.sslrootcert !== undefined) updated.sslrootcert = args.sslrootcert as string;

    sourcesConfig.set(srcName, updated);

    const fullConfig: SourcesConfig = {
      default: sourcesDefault,
      sources: Object.fromEntries(sourcesConfig),
      security: securityConfig,
    };

    try {
      writeSourcesFile(fullConfig);
    } catch (err: unknown) {
      // 回滚内存
      sourcesConfig.set(srcName, existing);
      const message = err instanceof Error ? err.message : String(err);
      return {
        content: [
          {
            type: 'text' as const,
            text: JSON.stringify({ success: false, error: message }, null, 2),
          },
        ],
      };
    }

    return {
      content: [
        {
          type: 'text' as const,
          text: JSON.stringify({ success: true, message: `数据源 ${srcName} 已更新` }, null, 2),
        },
      ],
    };
  }

  if (name === 'delete_source') {
    const srcName = args?.name as string | undefined;
    if (!srcName) {
      throw new McpError(ErrorCode.InvalidParams, '缺少必需参数: name');
    }

    ensureSourcesInitialized();

    if (!sourcesConfig.has(srcName)) {
      return {
        content: [
          {
            type: 'text' as const,
            text: JSON.stringify({ success: false, error: `数据源 "${srcName}" 不存在` }, null, 2),
          },
        ],
      };
    }

    if (sourcesConfig.size <= 1) {
      return {
        content: [
          {
            type: 'text' as const,
            text: JSON.stringify({ success: false, error: '不能删除唯一的数据源' }, null, 2),
          },
        ],
      };
    }

    sourcesConfig.delete(srcName);

    // 如果删除的是当前数据源，切换到默认
    if (currentSource === srcName) {
      currentSource = sourcesDefault;
      // 如果默认也被删除了，取第一个
      if (!sourcesConfig.has(currentSource)) {
        currentSource = Array.from(sourcesConfig.keys())[0];
        sourcesDefault = currentSource;
      }
    }

    // 如果删除的是默认数据源，重新选择
    if (sourcesDefault === srcName) {
      sourcesDefault = currentSource;
    }

    const fullConfig: SourcesConfig = {
      default: sourcesDefault,
      sources: Object.fromEntries(sourcesConfig),
      security: securityConfig,
    };

    try {
      writeSourcesFile(fullConfig);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        content: [
          {
            type: 'text' as const,
            text: JSON.stringify({ success: false, error: message }, null, 2),
          },
        ],
      };
    }

    return {
      content: [
        {
          type: 'text' as const,
          text: JSON.stringify({ success: true, message: `数据源 ${srcName} 已删除` }, null, 2),
        },
      ],
    };
  }

  if (name === 'switch_source') {
    const srcName = args?.source_name as string | undefined;
    if (!srcName) {
      throw new McpError(ErrorCode.InvalidParams, '缺少必需参数: source_name');
    }

    ensureSourcesInitialized();

    if (!sourcesConfig.has(srcName)) {
      return {
        content: [
          {
            type: 'text' as const,
            text: JSON.stringify({ success: false, error: `数据源 "${srcName}" 不存在` }, null, 2),
          },
        ],
      };
    }

    currentSource = srcName;
    return {
      content: [
        {
          type: 'text' as const,
          text: JSON.stringify(
            { success: true, current: srcName, message: `已切换到 ${srcName}` },
            null,
            2
          ),
        },
      ],
    };
  }

  if (name === 'test_connection') {
    const srcName = (args?.source_name as string | undefined) || currentSource;

    ensureSourcesInitialized();

    const dbConf = sourcesConfig.get(srcName);
    if (!dbConf) {
      return {
        content: [
          {
            type: 'text' as const,
            text: JSON.stringify({ success: false, error: `数据源 "${srcName}" 不存在` }, null, 2),
          },
        ],
      };
    }

    const startTime = Date.now();
    let client: Client | null = null;

    try {
      client = await createClient(dbConf);
      await client.query('SELECT 1');
      const responseTime = `${Date.now() - startTime}ms`;
      return {
        content: [
          {
            type: 'text' as const,
            text: JSON.stringify({ success: true, responseTime }, null, 2),
          },
        ],
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        content: [
          {
            type: 'text' as const,
            text: JSON.stringify(
              { success: false, error: message, responseTime: `${Date.now() - startTime}ms` },
              null,
              2
            ),
          },
        ],
      };
    } finally {
      if (client) {
        try {
          await client.end();
        } catch {
          // ignore close errors
        }
      }
    }
  }

  throw new McpError(ErrorCode.MethodNotFound, `未知工具: ${name}`);
});

// ============================================================================
// 启动服务
// ============================================================================

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error('PostgreSQL MCP Server 已启动（多数据源模式）');
}

main().catch((error) => {
  console.error('启动失败:', error);
  process.exit(1);
});
