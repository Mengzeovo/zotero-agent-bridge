# Zotero Pi Assistant

**当前版本：0.4.2** · **支持 Zotero 7–9（推荐 Zotero 9）** · **当前发行平台：Windows x64**

Zotero Pi Assistant 是一个嵌入 Zotero 的本地文献阅读助手。它把当前论文的 PDF、书目信息、Zotero 笔记与批注组织成结构化上下文，交给 Pi CLI 完成问答，并将会话和整理结果保存到本地。

它的目标不是把 Zotero 变成一个通用自动化平台，而是缩短“阅读论文 → 提问理解 → 延续讨论 → 沉淀笔记”这条工作链路。

> 本项目只保留 Zotero 内置 Pi 文献助手。通用 Agent Bridge、公共 CRUD API、MCP 工具、Obsidian 同步和论文自动归类已从 `0.4.1-beta` 起移除。

## 项目能做什么

| 能力 | 说明 |
| --- | --- |
| 文献上下文构建 | 读取当前 Zotero 条目的本地 PDF、元数据、子笔记和 PDF 批注，并保留页码信息。支持 Zotero 能够解析路径的 stored/linked PDF。 |
| Zotero 内置对话 | 在条目侧栏和 PDF Reader 侧栏中直接与 Pi 对话，无需在 Zotero 与独立终端之间反复切换。 |
| 连续流式问答 | 支持流式回答、中止生成、新建会话、模型切换和思考程度切换。 |
| 图片提问 | 支持纯图片或文字加图片的提问；格式包括 PNG、JPEG、WebP 和 GIF。 |
| 会话恢复 | 每篇论文使用独立的 Pi session；Zotero 或 Bridge 重启后可恢复当前会话，也可浏览、恢复历史会话和找回孤儿会话。 |
| 内容渲染 | 支持 Markdown、代码块和 KaTeX 公式；复制渲染后的公式时会恢复原始 LaTeX。 |
| 保存问答 | 用户确认后，将完整问题和回答保存为该论文的 Zotero 子笔记，并自动生成简短标题。 |
| 经验笔记 | 将新增问答增量整理为本地知识账本，再重建唯一的 `Pi 经验笔记`，用于持续积累知识单元、知识联系、认知修正和来源索引。 |
| 托管 Bridge | XPI 自带 Windows x64 Bridge，由插件负责校验、安装、启动、健康检查、回滚和停止；普通用户不需要安装 Python 或下载仓库源码。 |

## 它适合哪些场景

- 针对当前论文追问概念、方法、实验设计、结论和局限。
- 结合正文、Zotero 批注和已有笔记进行上下文连续的讨论。
- 在多次阅读之间恢复同一篇论文的历史会话。
- 把有价值的问答保存为 Zotero Note，减少手工复制和公式格式损失。
- 将分散在多个会话中的学习成果整理为可追溯、可重建的经验笔记。

它**不适合**以下用途：

- 扫描版或纯图片 PDF 的 OCR。
- Zotero 数据库的通用 CRUD、批量自动化或远程控制。
- MCP Server、Obsidian 同步、论文自动归类或通用 Agent 工具调用。
- 云端知识库、多设备实时同步或团队协作。

## 工作方式

```text
Zotero Add-on
    │  选中条目、收集 PDF/元数据/笔记/批注、展示聊天界面
    ▼
Local Bridge (127.0.0.1 + Token)
    │  构建阅读上下文、管理 Pi 进程、会话、历史与知识账本
    ▼
Pi CLI
    │  使用你配置的模型与凭据
    ▼
Model Provider
```

职责边界：

- **Zotero Add-on**：提供 UI、管理 Bridge 生命周期，并执行经过约束的 Zotero Note 写入。
- **Local Bridge**：只监听本机 loopback，负责阅读上下文、Pi RPC、会话持久化和经验笔记生成。
- **Pi CLI**：负责实际模型调用。项目不会替你安装 Pi，也不会提供模型账号或 API 凭据。

## 安装

### 使用前要求

- Windows x64。
- Zotero 7–9，推荐 Zotero 9。
- 已安装 Pi CLI，并已配置至少一个可用模型及对应凭据。
- 论文条目包含 Zotero 可访问的本地 PDF attachment。

### 安装步骤

1. 从 Releases 下载 `zotero-agent-bridge-addon-0.4.2.xpi`。
2. 在 Zotero 打开 **工具 → 插件 → Install Plugin From File…**。
3. 选择 XPI 并重启 Zotero。
4. 选中带本地 PDF 的论文，在条目侧栏或 PDF Reader 侧栏打开 **Pi 文献助手**。

插件会自动校验并安装自带 Bridge 到：

```text
%LOCALAPPDATA%\ZoteroAgentBridge\bridge\0.4.2
```

升级会保留 add-on ID、Bridge Token、Pi session 路径和文档 ID 规则。

## 基本使用

1. 在 Zotero 中选中一篇带可访问 PDF 的论文。
2. 打开 **Pi 文献助手**。
3. 选择模型和思考程度。
4. 输入问题；也可以附加图片后发送。
5. 等待回答完成，必要时中止生成或开始新会话。
6. 使用 **历史会话** 恢复旧对话。
7. 使用 **保存问答** 将当前完整问答写入 Zotero Note。
8. 使用 **更新经验笔记** 汇总该论文新增的学习成果。

为避免把回答写入错误的论文，只有活动论文、attachment、上下文指纹、Pi document ID 和已完成回答全部匹配时，Bridge 才允许保存笔记。

## 本地数据

受管数据默认保存在：

```text
%USERPROFILE%\Zotero\zotero-agent-bridge
├─ bridge.generated.json
├─ pi-chat\session-index.json
├─ pi-chat\experience-note-index.json
├─ pi-chat\experience-knowledge\*.json
└─ pi-sessions\*.jsonl
```

经验笔记使用三层数据模型：

1. **Pi JSONL**：原始会话，是可追溯来源。
2. **知识账本**：保存问答级证据、知识单元、关系和来源状态。
3. **Zotero `Pi 经验笔记`**：从账本确定性重建的阅读视图。

当来源会话缺失或损坏时，已经提取的知识不会被静默删除，而是保留并显示警告；“强制重建”则只使用当前仍可读取的来源重新生成账本。

## 安全与隐私边界

- Bridge 只监听 `127.0.0.1`，所有保留路由都要求插件管理的 API Token。
- Pi 使用 `--no-tools --no-skills --no-extensions --no-approve` 等限制参数启动。
- PDF、元数据、笔记和批注均被标记为不可信来源内容，不应被当作系统指令执行。
- Zotero 写入仅限“创建问答笔记”和“更新带固定标记的经验笔记”，且必须由用户确认触发。
- 已移除通用 CRUD、MCP、Obsidian 和任意脚本执行能力；旧 HTTP 路径只返回 `410 feature_retired`。
- 项目本身不提供云端同步，但 Pi 会把生成请求发送给你配置的模型提供商。实际数据保留、训练和隐私策略取决于该提供商及你的 Pi 配置。

## 当前局限性

1. **平台限制**：XPI 自带的 Bridge 目前只发布 Windows x64 版本。
2. **外部依赖**：必须单独安装和配置 Pi CLI、模型及凭据；模型可用性和响应质量不由本项目保证。
3. **PDF 提取限制**：使用文本提取而非 OCR。扫描版、图片型、加密或结构异常的 PDF 可能无法读取完整内容。
4. **上下文上限**：PDF、元数据、笔记和批注的完整上下文默认不能超过 `500,000` 字符；超限时会明确报错，不会静默截断。
5. **并发限制**：同一个 Bridge 实例同时只维护一个活动回答。
6. **本地持久化**：Pi session 和知识账本保存在本机；项目不提供云备份、多机同步或合并机制。
7. **图片限制**：每次最多 4 张图片，单张不超过 10 MiB，总大小不超过 20 MiB。
8. **产品范围限制**：不提供公共 OpenAPI、通用 Zotero 自动化接口、MCP、Obsidian 同步或论文归类。
9. **签名限制**：Bridge EXE 尚未进行 Authenticode 签名，Windows 可能显示来源或安全提示。

升级前仍建议备份 Zotero 数据和 `%USERPROFILE%\Zotero\zotero-agent-bridge`。

## 构建与测试

仅开发者从源码构建时需要 Python 3.12+、PowerShell、Node.js 和可调用的 Pi CLI：

```powershell
py -3.12 -m pip install -e .
py -3.12 -m unittest discover -s tests
powershell -ExecutionPolicy Bypass -File scripts\build_addon_xpi.ps1 -Version 0.4.2 -BuildBridge
```

主要输出：

```text
dist\zotero-agent-bridge-addon-0.4.2.xpi
dist\zotero-agent-bridge-addon.xpi
```

## 进一步文档

- [Pi 助手设计与接口](docs/PI_LITERATURE_ASSISTANT.md)
- [插件能力基线](docs/PI_PLUGIN_CAPABILITY_BASELINE.md)
- [Pi-only 退场策略](docs/PI_ONLY_RETIREMENT_POLICY.md)
- [Bridge bundle 协议](docs/BRIDGE_BUNDLE_PROTOCOL.md)

## License

[MIT](LICENSE)
