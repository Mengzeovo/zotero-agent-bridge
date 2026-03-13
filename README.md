# Zotero Agent Bridge v1 交付包

这是一个可独立交付的本机集成包，用来把 Zotero 和任意 agent 连接起来。

它包含两部分：
- `zotero-agent-bridge`：本机 HTTP JSON API + MCP Server
- `zotero_companion_addon`：运行在 Zotero 进程内的 companion add-on，负责执行写操作

建议先看：
- `docs/部署与使用说明.md`
- `config/bridge-config.example.json`
- `scripts/run_bridge.ps1`
- `scripts/run_mcp.ps1`
- `scripts/run_mcp.py`

## 你会得到什么

- 本机 HTTP API，供任何 agent 或脚本调用
- 本机 MCP Server，便于接入支持 MCP 的 agent
- Zotero 读写桥接能力
- PDF linked attachment 导入能力
- Markdown -> Zotero note 写入能力
- 本地镜像层，便于切换 agent 后继续复用论文、附件映射和笔记

## 目录说明

- `zotero_agent_bridge/`：Python bridge 服务源码
- `zotero_companion_addon/`：Zotero companion add-on 源码
- `tests/`：桥接层测试
- `config/bridge-config.example.json`：bridge 配置示例
- `scripts/run_bridge.ps1`：启动 HTTP bridge
- `scripts/run_mcp.ps1`：启动 MCP Server 的 PowerShell 包装脚本
- `scripts/run_mcp.py`：推荐给 Codex/MCP 客户端直接注册的 Python 入口
- `scripts/restructure_collections.ps1`：安装当前 Zotero 目录树
- `scripts/classify_papers.ps1`：按当前目录树批量归类论文
- `scripts/build_addon_xpi.ps1`：从 add-on 源码生成 `.xpi`
- `dist/`：已构建产物
- `docs/部署与使用说明.md`：完整中文文档

## 快速开始

1. 复制 `config/bridge-config.example.json` 为 `config/bridge-config.json`
2. 按你的机器路径修改配置
3. 确保 Zotero 已安装并启动
4. 安装 Python 依赖：`python -m pip install -e .`
5. 安装 add-on
6. 运行 `scripts/run_bridge.ps1`
7. 手动启动 MCP 时运行 `scripts/run_mcp.ps1`

完成桥接配置后，可选执行：

- `.\scripts\restructure_collections.ps1`
- `.\scripts\classify_papers.ps1`

详细步骤见 `docs/部署与使用说明.md`。
