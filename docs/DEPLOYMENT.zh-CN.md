# Zotero Agent Bridge v1 部署与使用说明

## 1. 这是什么

`Zotero Agent Bridge v1` 是一个运行在本机的中间层，用来把 Zotero 和任意 agent 解耦。

设计目标：
- 外部接口稳定，不依赖某一个特定 agent
- 读 Zotero 走 Local API
- 写 Zotero 走 Zotero companion add-on
- PDF 继续保存在独立文献仓中，Zotero 只维护 linked attachment
- 笔记以 Markdown 为主格式，Zotero note 为渲染后的副本
- 本地镜像层保存条目索引、附件映射、Markdown 笔记，便于换 agent 继续用

## 2. 运行形态

整体由 3 个部分组成：

1. 本机 HTTP Bridge 服务
- 监听 `127.0.0.1`
- 提供统一 JSON API
- 做 token 鉴权、写队列、操作日志、镜像更新

2. 本机 MCP Server
- 对外暴露 MCP 工具
- 内部转发到 HTTP Bridge
- 因此更换 agent 时，只需要更换 MCP 客户端，不需要重做 Zotero 集成

3. Zotero companion add-on
- 运行在 Zotero 进程内部
- 负责真正执行写操作
- 通过官方 Zotero JavaScript API 创建条目、修改条目、创建笔记、链接 PDF

## 3. 架构关系

```text
Agent
  | 
  | HTTP JSON / MCP
  v
zotero-agent-bridge (localhost)
  |
  | command/response files
  v
Zotero companion add-on (inside Zotero)
  |
  | official Zotero JS API
  v
Zotero Library

Mirror layer:
- metadata
- notes
- attachment mappings
- operation logs
```

## 4. 目录与职责

### 4.1 Bridge 代码
- `zotero_agent_bridge/`

职责：
- HTTP API
- MCP Server
- Local API 读取
- Add-on 命令队列客户端
- 镜像导出
- PDF 基础校验与 checksum
- DOI 元数据拉取

### 4.2 Add-on 代码
- `zotero_companion_addon/`

职责：
- 在 Zotero 进程内执行写操作
- 处理命令：
  - `create_item`
  - `update_item`
  - `attach_linked_pdf`
  - `create_note`
- 写入 add-on 状态文件，供 bridge 判断写能力是否可用

### 4.3 共享运行目录
由 `bridge_home` 决定，默认通常是：
- Windows: `%USERPROFILE%\Zotero\zotero-agent-bridge`

里面会有：
- `commands/`
- `responses/`
- `archive/`
- `logs/`
- `status/`
- `bridge.generated.json`

用途：
- bridge 把写命令写入 `commands/`
- add-on 从 `commands/` 读取并执行
- add-on 把结果写回 `responses/`
- `status/addon-status.json` 表示 add-on 是否在线
- `logs/operations.jsonl` 保存 bridge 写操作日志
- `bridge.generated.json` 保存自动生成的 API token

### 4.4 镜像目录
由配置决定，建议放在项目目录内：
- `metadata_dir`
- `notes_dir`

镜像层至少保存：
- 条目索引
- 附件映射
- Markdown 笔记
- 同步状态

字段包括：
- `library_id`
- `item_key`
- `attachment_key`
- `note_key`
- `slug`
- `pdf_path`
- `checksum`
- `updated_at`
- `sync_status`

## 5. 前置条件

你需要：
- Windows + Zotero 已安装
- Python 3.12+
- Zotero Local API 可访问
- 你的 PDF 放在独立文献仓中
- Zotero 运行在本机

注意：
- v1 写操作依赖 Zotero 正在运行
- Zotero 关闭时，镜像读取仍可用，但写操作会返回 `503`
- 不允许直接操作 `zotero.sqlite`

## 6. 配置文件

示例文件：
- `config/bridge-config.example.json`

建议复制为：
- `config/bridge-config.json`

关键配置：
- `host`: 默认 `127.0.0.1`
- `port`: 默认 `8765`
- `zotero_local_api_base`: 默认 `http://127.0.0.1:23119/api/users/0`
- `bridge_home`: bridge 和 add-on 共用的运行目录
- `metadata_dir`: 条目镜像目录
- `notes_dir`: Markdown 笔记镜像目录
- `base_attachment_path`: 你的独立 PDF 仓路径
- `api_token`: 可选；不填时自动生成

非常重要：
- 如果你修改了 `bridge_home`，必须把 `zotero_companion_addon/config/default-config.json` 里的 `bridgeHome` 改成同一个值
- bridge 和 add-on 的 `bridgeHome` 必须一致，否则写命令无法互相看到

## 7. 安装步骤

### 7.1 安装 Python 依赖
在本目录执行：

```powershell
python -m pip install -e .
```

### 7.2 准备 bridge 配置

```powershell
Copy-Item .\config\bridge-config.example.json .\config\bridge-config.json
```

然后编辑 `config/bridge-config.json`。

### 7.3 构建 add-on 安装包
已提供脚本：

```powershell
.\scripts\build_addon_xpi.ps1
```

产物会生成到：
- `dist/zotero-agent-bridge-addon.xpi`

如果已经存在这个文件，也可以直接使用。

### 7.4 在 Zotero 中安装 add-on
在 Zotero 中：
- 打开 `Tools -> Add-ons`
- 点击齿轮图标
- 选择 `Install Add-on From File...`
- 选中 `dist/zotero-agent-bridge-addon.xpi`
- 重启 Zotero

### 7.5 启动 Bridge 服务

```powershell
.\scripts\run_bridge.ps1
```

默认会读取：
- `config/bridge-config.json`

### 7.6 启动 MCP Server
在另一个终端里执行：

```powershell
.\scripts\run_mcp.ps1
```

说明：
- `run_mcp.ps1` 是便于手动启动的包装脚本
- 如果要给 Codex Desktop / Codex CLI 注册 MCP，推荐直接注册 `scripts/run_mcp.py`
- 这样更容易让桌面端正确识别 `cwd`、`startup_timeout_sec` 和 UTF-8 环境变量

## 8. 如何判断是否正常运行

### 8.1 检查 bridge

```powershell
$cfg = Get-Content .\config\bridge-config.json | ConvertFrom-Json
$token = (Get-Content "$($cfg.bridge_home)\bridge.generated.json" | ConvertFrom-Json).api_token
Invoke-RestMethod -Headers @{"X-Bridge-Token"=$token} -Uri "http://$($cfg.host):$($cfg.port)/health"
```

### 8.2 检查能力状态

```powershell
Invoke-RestMethod -Headers @{"X-Bridge-Token"=$token} -Uri "http://$($cfg.host):$($cfg.port)/capabilities"
```

关键字段：
- `read=true`：说明 Local API 或镜像读取可用
- `write=true`：说明 Zotero 正在运行且 add-on 在线

## 9. 对外 HTTP API

所有请求都要带：
- `X-Bridge-Token: <token>`
或：
- `Authorization: Bearer <token>`

接口如下：
- `GET /health`
- `GET /capabilities`
- `GET /items/search?q=...`
- `GET /items/{itemKey}`
- `POST /items`
- `PATCH /items/{itemKey}`
- `POST /items/{itemKey}/attachments/linked-pdf`
- `POST /items/{itemKey}/notes`
- `POST /sync/export`

### 9.1 创建条目
`POST /items`

支持 3 种入口：
- `doi`
- `pdf_path`
- `manual_fields`

示例：

```json
{
  "doi": "10.1000/demo-doi"
}
```

或者：

```json
{
  "pdf_path": "E:/papers/inbox/demo.pdf"
}
```

或者：

```json
{
  "manual_fields": {
    "item_type": "journalArticle",
    "fields": {
      "title": "A Demo Paper",
      "date": "2025",
      "DOI": "10.1000/demo-doi"
    },
    "creators": [
      {
        "creatorType": "author",
        "firstName": "Alice",
        "lastName": "Zhang"
      }
    ]
  }
}
```

### 9.2 更新条目
`PATCH /items/{itemKey}`

需要带 `version`，用于乐观并发控制。
旧版本提交会返回 `409`。

### 9.3 导入 linked PDF
`POST /items/{itemKey}/attachments/linked-pdf`

示例：

```json
{
  "pdf_path": "E:/papers/curated/demo.pdf",
  "title": "Demo PDF"
}
```

### 9.4 创建笔记
`POST /items/{itemKey}/notes`

示例：

```json
{
  "title": "Reading Note",
  "markdown": "# Main Idea\n\nThis paper focuses on ..."
}
```

v1 规则：
- Markdown 是主格式
- bridge 会把 Markdown 渲染成 Zotero note HTML
- 当前只做单向同步：`Markdown -> Zotero`

### 9.5 导出镜像
`POST /sync/export`

用途：
- 把 Zotero 条目导出到本地镜像层
- 用于重建镜像或跨 agent 共享上下文

## 10. MCP 工具

MCP 工具名固定为：
- `search_items`
- `create_item`
- `update_item`
- `import_pdf`
- `create_note`
- `export_item`

建议把 MCP Server 配置为：

```text
command: <absolute-python-path>
args:
  - <this-package-root>/scripts/run_mcp.py
cwd: <this-package-root>
startup_timeout_sec: 30
env:
  PYTHONUTF8: "1"
```

这样任何支持 MCP 的 agent 都能复用同一套 Zotero 集成。

当前 MCP server 除了 tools 外，还会声明以下资源，便于桌面端更稳定地识别：
- `zotero://server/info`
- `zotero://bridge/health`
- `zotero://bridge/capabilities`
- `zotero://items/{item_key}`

## 11. PDF 处理策略

v1 固定策略：
- 只支持 `linked attachment`
- 不把 PDF 复制进 Zotero storage
- PDF 仍保存在你自己的独立文献仓里

导入流程：
1. 校验文件存在且后缀为 PDF
2. 计算 checksum
3. 先按 DOI 去重
4. 再按 checksum 去重
5. 创建或定位父条目
6. 在 Zotero 中创建 linked attachment
7. 更新镜像索引

元数据解析顺序：
1. 显式 DOI
2. PDF 识别
3. 手填字段
4. 占位条目并标记 `needs_review`

## 12. 错误约定

固定错误码：
- `409`: 重复条目、重复 PDF、版本冲突
- `422`: PDF 无效、元数据不足、Markdown 渲染失败、请求字段不合法
- `503`: Zotero 或 add-on 不可用

## 13. 典型运行状态

### Zotero 正在运行 + add-on 在线
- `capabilities.write = true`
- 可以创建条目、更新条目、导入 PDF、创建笔记

### Zotero 未运行
- `capabilities.write = false`
- 可继续读镜像
- 写接口返回 `503`

### add-on 不可用
- 读能力仍可保留
- 写能力降级为不可用

## 14. 你真正需要记住的 3 件事

1. `bridge` 是本机服务，不是云服务
2. `add-on` 必须装在 Zotero 里，并且和 bridge 使用同一个 `bridge_home`
3. `PDF` 继续放在你自己的独立文献仓中，Zotero 只做 linked attachment

## 15. 建议的落地目录

如果你要单独维护这个项目，推荐结构：

```text
zotero-agent-bridge-v1/
  config/
  dist/
  docs/
  scripts/
  tests/
  zotero_agent_bridge/
  zotero_companion_addon/
  pyproject.toml
  README.md
```

## 16. 故障排查

### 问题 1：`write=false`
检查：
- Zotero 是否已启动
- add-on 是否已安装并重启 Zotero
- `status/addon-status.json` 是否存在
- bridge 和 add-on 的 `bridgeHome` 是否一致

### 问题 2：能读不能写
通常说明：
- Local API 正常
- 但 add-on 没启动或没连上共享目录

### 问题 3：PDF 挂接失败
检查：
- 路径是否真实存在
- 是否为 `.pdf`
- `base_attachment_path` 是否与 Zotero 的相对附件配置一致

### 问题 4：换了 agent 后不能用
检查：
- 是否仍然连到同一个 HTTP bridge
- 或 MCP 是否仍然指向同一个本机 bridge
- token 是否正确

## 17. 当前验证情况

本交付包已经完成：
- Python 语法编译检查
- HTTP / MCP 主流程测试
- 创建条目、更新条目、导入 PDF、创建笔记、导出镜像测试
- 版本冲突和 PDF 去重测试

尚未完成的唯一现场步骤：
- 在你机器上的真实 Zotero 进程中做一次 add-on 联调 smoke test

这一步建议在你准备正式接入日常工作流时执行一次。
