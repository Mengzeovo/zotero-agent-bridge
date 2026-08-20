# Zotero Agent Bridge v1 交付包

这是一个可独立交付的本机集成包，用来把 Zotero 和任意 agent 连接起来。

它现在按产品职责拆成三部分：
- `zotero_agent_bridge/`：Python bridge core，本机 HTTP JSON API + MCP Server
- `zotero_companion_addon/`：运行在 Zotero 进程内的 companion add-on，负责执行 Zotero 写操作
- `obsidian_bridge_plugin/`：运行在 Obsidian Desktop 内的主控插件，负责配置、启动和管理 Python bridge 进程

建议先看：
- `docs/部署与使用说明.md`
- `docs/PI_LITERATURE_ASSISTANT.md`
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
- Zotero 9 Item Pane 内置 Pi 文献助手，读取 PDF 全文、笔记和批注，并在明确确认后把最终回答保存为 Zotero Note

## 目录说明

- `zotero_agent_bridge/`：Python bridge 服务源码
- `zotero_companion_addon/`：Zotero companion add-on 源码，只放 Zotero 插件代码
- `obsidian_bridge_plugin/`：Obsidian Desktop 插件源码，只放 Obsidian 插件代码
- `tests/`：桥接层测试
- `config/bridge-config.example.json`：bridge 配置示例
- `scripts/run_bridge.ps1`：启动 HTTP bridge
- `scripts/run_mcp.ps1`：启动 MCP Server 的 PowerShell 包装脚本
- `scripts/run_mcp.py`：推荐给 Codex/MCP 客户端直接注册的 Python 入口
- `scripts/restructure_collections.ps1`：安装当前 Zotero 目录树
- `scripts/classify_papers.ps1`：按当前目录树批量归类论文
- `scripts/build_bridge_windows.ps1`：使用 PyInstaller 构建 Windows x64 自包含 Bridge
- `scripts/build_addon_xpi.ps1`：校验 Bundle 并生成内含 Bridge 的确定性 `.xpi`
- `scripts/build_obsidian_plugin.ps1`：生成 Obsidian 插件目录，可选复制到 vault 的插件目录
- `dist/`：已构建产物
- `docs/部署与使用说明.md`：完整中文文档

## 快速开始

1. 安装 Pi CLI，并确认命令行中可以运行 `pi`
2. 在 Zotero 9 中安装 `dist/zotero-agent-bridge-addon-0.3.0.xpi`
3. 启动 Zotero；XPI 会自动释放、校验并启动内置 Windows x64 Bridge
4. 选择带本地 PDF 的文献，从 Item Pane 打开“Pi 文献助手”
5. 首次打开文献会话时，Bridge 使用外部 Pi CLI；保存 Zotero Note 仍需明确确认
6. 若已有兼容 Bridge 在运行，插件会将其视为 shared 实例，退出 Zotero 时不会关闭它

0.3.0 Beta 不需要安装 Python、pip、项目源码或执行启动器注册脚本。当前 EXE 未进行 Authenticode 签名，Windows SmartScreen 或杀毒软件可能显示提示。

源码开发、独立 MCP/Obsidian Bridge 和兼容旧部署时，仍可使用 `config/bridge-config.example.json`、`scripts/run_bridge.ps1` 与 legacy launcher 脚本。

完成桥接配置后，可选执行：

- `.\scripts\restructure_collections.ps1`
- `.\scripts\classify_papers.ps1`

详细步骤见 `docs/部署与使用说明.md`。
