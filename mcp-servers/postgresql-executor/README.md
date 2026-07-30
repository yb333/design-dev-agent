# PostgreSQL / Huawei Cloud DWS MCP Server

支持多数据源管理的 MCP Server，可在 PostgreSQL 或华为云 DWS 数据库中执行 SQL。

## 功能

### SQL 执行（3 个）
- `execute_sql` - 执行 SQL 语句，返回结果
- `list_tables` - 列出数据库中的所有表
- `describe_table` - 查看表结构

### 数据源管理（6 个）
- `list_sources` - 列出所有已配置的数据源（密码脱敏）
- `add_source` - 添加新数据源
- `update_source` - 更新数据源配置（部分更新）
- `delete_source` - 删除数据源
- `switch_source` - 切换当前活跃数据源（无需重启）
- `test_connection` - 测试数据源连通性

## 安装

```bash
cd mcp-servers/postgresql-executor
npm install
npm run build
```

## 配置

### 多数据源配置（推荐）

1. 复制配置文件：
```bash
cp db-sources.example.json db-sources.json
```

2. 修改 `db-sources.json`：
```json
{
  "default": "local-dev",
  "sources": {
    "local-dev": {
      "type": "postgresql",
      "host": "localhost",
      "port": 5432,
      "database": "your_database",
      "user": "your_user",
      "password": "your_password",
      "ssl": false
    },
    "dws-prod": {
      "type": "huawei-dws",
      "host": "your-dws-cluster.huaweicloud.com",
      "port": 8000,
      "database": "your_database",
      "user": "your_user",
      "password": "${DWS_PROD_PASSWORD}",
      "ssl": true,
      "sslrootcert": "/path/to/dws-ca.pem"
    }
  },
  "security": {
    "allowWriteOperations": false,
    "maxRows": 100,
    "timeout": 0
  }
}
```

### 密码安全

支持环境变量引用，避免在配置文件中明文存储密码：

```json
{
  "password": "${MY_DB_PASSWORD}"
}
```

运行时自动从 `process.env.MY_DB_PASSWORD` 读取。未设置则使用原始字符串作为密码。

### 向后兼容

如果 `db-sources.json` 不存在，自动回退读取 `db-config.json` 作为名为 `default` 的单一数据源。

## OpenCode 集成

### 方式 1：配置到 opencode.json

编辑 `~/.config/opencode/opencode.json`：

```json
{
  "mcp": {
    "postgresql-executor": {
      "type": "local",
      "command": ["node", "/path/to/postgresql-executor/dist/index.js"],
      "environment": {
        "DB_CONFIG": "/path/to/postgresql-executor/db-sources.json"
      }
    }
  }
}
```

### 方式 2：使用 opencode mcp add 命令

```bash
opencode mcp add
# 然后按照提示输入配置
```

## 使用示例

在 OpenCode 中：

```
# SQL 操作
列出所有表
查看 users 表的结构
执行 SQL：SELECT * FROM users LIMIT 10

# 数据源管理
列出所有数据源
帮我添加一个数据源，名称 dws-test，类型 huawei-dws，地址 192.168.1.100，端口 8000，数据库 dw_test，用户 etl_read
切换到 dws-test
测试 dws-test 的连接
把 dws-test 的端口改成 8001
删除 dws-test 数据源
```

## 安全说明

- 默认**只允许 SELECT 查询**（`allowWriteOperations: false`）
- 返回行数默认限制 100 行（`maxRows: 100`），避免大量数据消耗 AI 上下文
- 查询超时默认不限制（`timeout: 0`），由数据库 `statement_timeout` 控制
- 设置 `timeout > 0` 可启用 MCP 层超时（使用 pg 原生 query timeout）
- `list_sources` 不返回密码值（脱敏处理）
- 密码支持环境变量引用：`"password": "${MY_DB_PASSWORD}"`

## 项目结构

```
postgresql-executor/
├── package.json
├── tsconfig.json
├── src/
│   └── index.ts              # MCP server 入口（多数据源支持）
├── db-sources.example.json   # 多数据源配置示例
├── db-sources.json           # 实际配置（需创建，含密码不上传）
├── db-config.example.json    # 旧版单数据源配置示例（向后兼容）
└── README.md
```

## 故障排查

**错误：配置文件不存在**
```bash
cp db-sources.example.json db-sources.json
# 然后修改配置
```

**错误：写操作已被禁用**
- 在 `db-sources.json` 中设置 `security.allowWriteOperations: true`

**错误：连接超时**
- 检查 host、port 是否正确
- 检查网络是否可达
- 增加 `security.timeout` 值

**错误：不能删除唯一的数据源**
- 至少需要保留一个数据源，请先添加新数据源再删除

## License

MIT
