# Zotero Pi Assistant

**当前版本：0.4.2-beta**

Zotero Pi Assistant 是运行在 Zotero Item Pane 内的 Pi 文献助手。它读取当前论文的本地 PDF、Zotero 子笔记与批注，提供可恢复的连续对话，并在用户确认后把最终回答保存为 Zotero Note。

本项目只提供 Zotero 内置 Pi 文献助手。通用 Agent Bridge、公共 CRUD API、MCP 工具、Obsidian 同步和论文归类实现均已从 `0.4.1-beta` 物理删除；旧 HTTP 路径仅保留需要 Bridge Token、无副作用并返回 `410 feature_retired` 的兼容墓碑。

## 功能

- Zotero 7–9 Item Pane 内置聊天面板，推荐 Zotero 9。
- 自动读取当前条目的本地 PDF、元数据、笔记、批注和页码。
- Pi 流式回答、中止、重置、模型切换与思考程度切换。
- 每篇论文独立保存 Pi session，支持历史列表、孤儿会话找回、恢复并继续提问。
- Markdown、KaTeX 公式和代码渲染。
- 复制公式时恢复原始 `$...$`、`$$...$$`、`\(...\)` 或 `\[...\]` LaTeX。
- “保存问答”在用户确认后新建结构化 Zotero Note，由独立的无会话 Pi 生成不超过 15 个可见字符的标题，并保留公式中的 `<`、`>`、`&`。
- “更新经验笔记”把原始会话增量整理为本地知识账本，再从知识单元、知识联系、认知修正和来源索引确定性重建唯一的 `Pi 经验笔记`。未变化问答不再调用 Pi；来源会话缺失后已提取知识继续保留并显示警告。
- XPI 自带并管理 Windows x64 Bridge；普通用户不需要 Python 或仓库源码。

## 安装

1. 从 Releases 下载 `zotero-agent-bridge-addon-0.4.2-beta.xpi`。
2. 在 Zotero 打开 **工具 → 插件 → Install Plugin From File…**。
3. 选择 XPI 并重启 Zotero。
4. 选中带本地 PDF 的论文，在 Item Pane 打开 **Pi 文献助手**。

插件会校验并安装自带 Bridge 到：

```text
%LOCALAPPDATA%\ZoteroAgentBridge\bridge\0.4.2-beta
```

受管数据继续使用稳定路径：

```text
%USERPROFILE%\Zotero\zotero-agent-bridge
├─ bridge.generated.json
├─ pi-chat\session-index.json
├─ pi-chat\experience-note-index.json
├─ pi-chat\experience-knowledge\*.json
└─ pi-sessions\*.jsonl
```

经验笔记使用三层数据模型：原始 Pi JSONL 是可追溯来源，知识账本保存问答级证据、知识单元、关系和来源状态，Zotero `Pi 经验笔记` 是可从账本重新渲染的阅读视图。来源会话丢失或损坏时，已经提取的学习成果不会静默消失；“强制重建”则只从当前可读取来源重新建立账本。超大账本的跨分区关系审计受调用预算约束；预算不足时会保留已验证关系、完成更新并显示明确警告，而不是无限调用或丢弃知识单元。

升级不会更改 add-on ID `zotero-agent-bridge@local`、API Token、Pi session 路径或文档 ID 算法。

## 使用

1. 选中带可访问 PDF attachment 的 Zotero 条目。
2. 打开 Pi 文献助手。
3. 选择模型与思考程度。
4. 输入问题并等待回答结束。
5. 使用“历史会话”恢复旧对话，或“重置”开始新会话。
6. 点击“保存为 Zotero Note”并确认。

只有活动论文、活动 Pi document ID 和已完成回答完全匹配时，Bridge 才允许保存笔记。

## 安全边界

- Bridge 只监听 loopback，并要求插件管理的 API Token。
- Pi 使用 `--no-tools --no-skills --no-extensions --no-approve` 等限制参数启动。
- PDF、笔记和批注被视为不可信来源材料。
- Zotero 写入仅允许专用 `create_assistant_note` 与带固定标记校验的 `upsert_assistant_experience_note`，且均由用户确认触发。
- 旧 CRUD、MCP、Obsidian 和通用脚本已不存在；仅保留插件面板所需的私有 Pi 路由。

## 构建与测试

要求 Python 3.12+、PowerShell、Node.js，以及可调用的 Pi CLI。

```powershell
py -3.12 -m pip install -e .
py -3.12 -m unittest discover -s tests
powershell -ExecutionPolicy Bypass -File scripts\build_addon_xpi.ps1 -Version 0.4.2-beta -BuildBridge
```

主要输出：

```text
dist\zotero-agent-bridge-addon-0.4.2-beta.xpi
dist\zotero-agent-bridge-addon.xpi
```

## 文档

- [Pi 助手设计与接口](docs/PI_LITERATURE_ASSISTANT.md)
- [插件能力基线](docs/PI_PLUGIN_CAPABILITY_BASELINE.md)
- [Pi-only 退场策略](docs/PI_ONLY_RETIREMENT_POLICY.md)
- [Bridge bundle 协议](docs/BRIDGE_BUNDLE_PROTOCOL.md)

## 当前限制

- 自带 Bridge 目前仅发布 Windows x64。
- Pi CLI 需要单独安装并配置模型凭据。
- 同一 Bridge 同时只维护一个活动回答。
- 不提供扫描 PDF OCR、云端同步或多机 session 同步。
- Bridge EXE 尚未进行 Authenticode 签名。

## License

[MIT](LICENSE)
