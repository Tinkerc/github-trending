# GitHub Trending JSON 采集与飞书通知方案

状态：设计草案，尚未实施  
日期：2026-11-14  
适用范围：后续采集、数据归档、GitHub Actions 与飞书通知

## 1. 设计目标与边界

将后续运行的数据源从 Markdown 改为结构化 JSON，补充全语言日榜、周榜，并支持飞书自定义机器人通知。继续使用 Python、GitHub Actions 和 Git 仓库，不新增数据库服务或依赖复杂的基础设施。

本期明确不做：

- 不扫描、解析、迁移或删除历史 Markdown，也不改写 Git 历史。
- 不修改历史分析脚本 `analysis.py`；该脚本继续只适用于旧 Markdown。
- 不开发网页、查询 API、数据库服务或历史回填工具。
- 不采集 GitHub Trending 之外的仓库详情，不额外调用 GitHub API。

JSON 在这里承担版本化数据存储的职责，不提供数据库索引和事务能力。采用结构化存储是为了便于复用和减少重复字段，不承诺改成 JSON 后文件体积必然下降。

## 2. 当前实现与改造边界

| 位置 | 当前行为 | 目标行为 |
| --- | --- | --- |
| `scraper.py` | 固定采集六个语言，将结果追加到当日 Markdown | 返回结构化条目，校验后写入 JSON |
| `analysis.py` | 解析历史 Markdown 并导出 CSV | 本期保持原样 |
| `.github/workflows/main.yml` | 定时和 push 时采集，提交整个工作区 | 校验与采集分开，只提交 `data/` |
| `.github/workflows/schedule.yml` | 与 main 工作流在同一时间重复采集 | 合并到单一采集入口 |
| 通知 | 当前仓库代码中未找到企微 webhook 实现 | 新增飞书通知模块 |

移除采集脚本中无关的邮箱环境变量读取、凭据打印，以及未使用的 Git 提交辅助函数。Git 操作统一由 Actions 执行，采集脚本本地运行时只生成数据。

## 3. 数据结构

### 3.1 文件组织

```text
data/
  repos.json
  snapshots/
    2026/
      11/
        2026-11-15.json
```

- `repos.json`：去重后的仓库目录，保存最新观察到的名称、URL、描述和实际语言。
- 每日快照：保存当日各榜单的排名和数值指标，通过 `repo_key` 引用仓库目录。
- 不再生成新的日期 Markdown。历史年份目录保留。

初期采用单个 `repos.json`，便于人工检查和使用标准库读写。只有当实际体积或运行耗时成为问题时，再评估分片；本期不引入分片算法。

### 3.2 仓库目录示例

以下内容为结构示例，不代表真实榜单或指标。

```json
{
  "schema_version": 1,
  "repositories": {
    "example/project": {
      "full_name": "Example/Project",
      "url": "https://github.com/Example/Project",
      "description": "示例项目",
      "language": "Python",
      "first_seen": "2026-11-15",
      "last_seen": "2026-11-15"
    }
  }
}
```

| 字段 | 类型与含义 |
| --- | --- |
| `schema_version` | 整数；不兼容结构变更时递增 |
| `repositories` | 对象；键为规范化的 `repo_key` |
| `repo_key` | `owner/name` 转小写；从仓库链接提取，不从显示文本拼接 |
| `full_name` | 保留 GitHub 链接提供的大小写，用于展示 |
| `description` | 字符串；未提供描述时为空字符串 |
| `language` | 字符串或 `null`；项目实际语言，不等同于榜单筛选条件 |
| `first_seen` / `last_seen` | 在新 JSON 数据中首次、最近观察到的业务日期 |

仓库目录不保存排名和 stars，避免同一项目在多个榜单出现时相互覆盖指标。项目不再上榜时保留目录条目。同次采集的元数据按固定榜单顺序合并，结果确定。

限制：不查询 GitHub 仓库 ID，因此重命名和转移后的仓库按新键记录，不自动合并。`first_seen` 不代表该仓库历史上第一次上榜。

目录只保留最新元数据，旧快照的排名和指标可以复现，旧描述文本不能精确复现；这是减少重复描述的明确取舍。

### 3.3 每日快照示例

```json
{
  "schema_version": 1,
  "date": "2026-11-15",
  "timezone": "Asia/Shanghai",
  "fetched_at": "2026-11-15T02:00:12Z",
  "boards": [
    {
      "period": "daily",
      "language_filter": "all",
      "source_url": "https://github.com/trending?since=daily",
      "entries": [
        {
          "rank": 1,
          "repo_key": "example/project",
          "stars": 12345,
          "forks": 678,
          "stars_in_period": 321
        }
      ]
    },
    {
      "period": "weekly",
      "language_filter": "all",
      "source_url": "https://github.com/trending?since=weekly",
      "entries": [
        {
          "rank": 1,
          "repo_key": "example/project",
          "stars": 12345,
          "forks": 678,
          "stars_in_period": 1500
        }
      ]
    }
  ]
}
```

| 字段 | 类型与规则 |
| --- | --- |
| `date` | 上海时区下的采集日期，`YYYY-MM-DD`；一次运行固定使用同一日期 |
| `fetched_at` | 本次采集开始时的 UTC 时间，ISO 8601 格式 |
| `boards` | 榜单数组，按配置顺序保存 |
| `period` | `daily` 或 `weekly`；使用 GitHub 参数原值 |
| `language_filter` | `all` 或规范化小写语言 slug，例如 `python`、`typescript` |
| `source_url` | 实际请求的榜单地址 |
| `entries` | 按页面顺序排列的条目数组 |
| `rank` | 从 1 开始且连续的整数 |
| `stars` / `forks` | 页面提供的累计值，非负整数；字段缺失时为 `null` |
| `stars_in_period` | 页面展示的本榜单周期增长值，非负整数；缺失时为 `null` |

`stars_in_period` 直接使用页面数据，不通过两次累计 stars 相减推导；GitHub weekly 的精确时间边界与排名算法不在本项目定义范围内。

### 3.4 一致性与重复运行

- 同一快照内，`(period, language_filter)` 唯一；同一榜单内 `repo_key` 唯一。
- 每个快照引用的仓库必须存在于更新后的仓库目录。
- 同一天重跑覆盖同一路径，不创建第二份快照、不追加重复记录。新采集时间和页面变化可以产生新版本，不要求字节级不变。
- 数值解析识别千分位；非空但无法解析的值报错，不静默写成 0。缺失值使用 `null`。
- UTF-8 编码、保留中文、固定缩进，仓库对象键排序，减少无关差异。
- 所有配置榜单成功且校验通过后才进入写入阶段，先写临时文件，再原子替换单个目标文件。抓取或校验失败时不修改已有 JSON。
- 两个文件不具备跨文件原子事务；先替换仓库目录再替换快照。写入中途失败时进程失败，Actions 不提交；下次运行可恢复。Git 提交作为仓库对外的一致性边界。

## 4. 采集范围与可靠性

默认每天采集八个榜单：

| 范围 | 周期 | 数量 |
| --- | --- | --- |
| 全语言总榜 | daily、weekly | 2 |
| python、javascript、go、html、typescript、java | daily | 6 |

每个榜单采集页面实际返回的全部条目，不假定固定条目数。周榜每天记录一次当前快照，不聚合日榜，也不只在某个周末采集。

语言列表使用 `TRENDING_LANGUAGES` 配置，逗号分隔；未配置时采用上述六种语言。总榜始终启用。语言周榜不在本期默认范围内。

请求设置连接和读取超时，对连接失败、429 和部分 5xx 做有限重试与退避；不无限重试。使用链接结构提取仓库、明确选择器提取指标，避免把 star、fork 和增长数混在一起。

页面为 200 不代表成功：空榜、缺少仓库链接、重复仓库或结构异常均使本次采集失败，保留已有快照。该策略可能把真实空榜判为失败，优先避免错误覆盖。

## 5. 飞书通知

### 5.1 配置与签名

| GitHub 配置 | 类型 | 用途 |
| --- | --- | --- |
| `FEISHU_WEBHOOK_URL` | Repository Secret | 用户提供的机器人 webhook，不写入源码、文档示例和日志 |
| `FEISHU_SIGNING_SECRET` | Repository Secret | 飞书机器人签名密钥，可在启用签名校验时补充 |
| `TRENDING_LANGUAGES` | Repository Variable | 可选；配置语言列表 |

Actions 通过环境变量传给脚本。不保存固定 `signature`：配置签名密钥后，每次发送动态生成秒级 `timestamp` 和 `sign`。

签名公式遵循飞书官方约定：

```text
key  = UTF8(timestamp + "\n" + signing_secret)
sign = Base64(HMAC-SHA256(key, empty_message))
```

未配置 webhook 时跳过通知并给出不含敏感信息的提示。未配置密钥时不附加签名字段，适用于尚未启用签名校验的机器人；机器人启用签名校验后，必须同时配置 Secret。

### 5.2 内容与发送时机

初版使用飞书 `text` 消息：采集日期、总榜日榜 Top 10、总榜周榜 Top 10、仓库名称及链接、周期增长量，以及本次归档链接。语言榜保留在 JSON 中，不逐榜发送。

消息按 UTF-8 请求体字节数限制长度，保持低于飞书 20 KB 上限；超限时减少条目。暂不实现首次上榜识别，避免缺少历史基线时产生误导。

通知在数据成功提交并推送后发送。发送接口除检查 HTTP 状态外，还检查响应 JSON 的 `code == 0`。错误日志不输出完整请求 URL 或密钥。

推送失败不回滚已保存的数据，但 Actions 标记失败，便于发现。提供独立的 `--notify-only` 入口，默认从当天已保存快照发送通知；可通过 `--date YYYY-MM-DD` 指定重发日期，无需重新抓取。Actions 使用采集步骤写入 `GITHUB_OUTPUT` 的日期传给通知，跨午夜也读取本次快照。通知重试可能重复发送，本期不承诺严格一次投递。

## 6. GitHub Actions 运行流程

保留单一采集工作流，支持每天 UTC 02:00（上海时间 10:00）定时运行，以及 `workflow_dispatch` 手动运行。push / pull request 只执行校验，不抓取、不提交、不通知。

```text
检出默认分支 → 安装依赖 → 测试
  → 抓取八个榜单 → 校验 → 写入 JSON
  → 仅暂存 data/ → 有差异才提交 → 推送成功
  → 从快照发送飞书摘要
```

- 固定 `ubuntu-24.04` 与 Python `'3.12'`，避免 `ubuntu-latest` 自动切换操作系统；更新 Actions 到受支持的版本。
- 采集任务声明 `contents: write`；验证任务只读。
- 采集使用独立并发组，`cancel-in-progress: false`，防止正在执行的归档被新任务中断。
- 不使用 `git add -A`，避免提交与数据无关的文件；无差异时跳过提交。
- 默认分支由仓库上下文确定，不写死 `master`。
- 非默认分支手动运行只执行验证，不归档或通知；归档检出默认分支最新代码并重新测试，避免队列等待后使用旧提交。
- 自动提交遵守仓库 Lore 提交约定，说明归档目的与校验结果。
- 推送失败时不发送成功通知，不使用强制推送。分支保护若阻止机器人写入，需要在实际配置时解决。

### 6.1 最近 Python 安装失败的诊断与修复

用户提供的失败日志停在 `actions/setup-python@v2`：

```text
Version 3.8 was not found in the local cache
Error: Version 3.8 with arch x64 not found
```

**已确认**：失败发生在 Python 安装阶段，尚未安装业务依赖、运行采集或执行通知。两个现有工作流均配置 `ubuntu-latest`、`setup-python@v2` 和 Python 3.8，均需要调整。`punycode` 和 `url.parse()` 的弃用提示是 Action 所在 Node 环境的警告，此日志中的直接终止原因是找不到 Python 发行包。

**高概率原因**：runner 操作系统更新后，旧 Python 版本与实际镜像无法匹配。GitHub 公告说明 `ubuntu-latest` 在 2026-10-19 至 2026-11-19 逐步从 Ubuntu 24.04 切换到 26.04；本次故障时间落在窗口内。核验时官方 Python manifest 有 3.8 的 Linux x64 / 24.04 构建，但没有 26.04 构建；Python 3.12 两者均有构建。因此不能笼统说 Python 3.8 在所有 runner 上都无法使用，也不能仅升级 Action 就保证旧 Python 可安装。

**尚未确认**：用户提供的片段没有 `Set up job` 中的 Image 和 Image Version，不能断言该次任务实际使用了 Ubuntu 26.04。后续可用完整日志确认具体镜像，不影响采用显式环境组合的修复方向。

目标环境示例（实施时应用，不代表当前工作流已修复）：

```yaml
runs-on: ubuntu-24.04
steps:
  - uses: actions/checkout@v6
  - uses: actions/setup-python@v6
    with:
      python-version: '3.12'
      cache: pip
  - run: python --version
  - run: python -m pip install -r requirements.txt
```

版本字符串加引号；`setup-python@v6` 使用 Node 24，要求 runner 至少为 v2.327.1，面向本项目的 GitHub 托管 runner 使用。固定 OS 是避免操作系统自动迁移，并不冻结镜像内所有软件版本。

验证时先确认 Python 版本和依赖安装成功，再运行解析测试与 JSON 采集冒烟检查，最后独立验证通知。当前只记录设计修复，未修改工作流、未重跑远端任务，也未验证依赖在新环境下的兼容性。

## 7. 代码职责与验证

预计修改或新增的文件：

| 文件 | 职责 |
| --- | --- |
| `scraper.py` | 配置、采集、解析、JSON 校验与保存，普通运行不发送通知 |
| `notify.py` | 飞书消息构造、签名、发送及业务响应检查 |
| `.github/workflows/main.yml` | 验证和定时采集编排 |
| `.github/workflows/schedule.yml` | 删除重复入口 |
| `tests/` | 页面 fixture、解析、保存、签名和发送的针对性测试 |
| `README.md` | 更新运行说明、JSON 位置与 Secrets 配置 |

`scraper.py --notify-only` 调用通知模块，且要求指定日期（默认当天）的快照存在。测试使用标准库 `unittest`、临时目录和 HTTP mock，不新增测试框架，不真实发送消息。

实施验证清单：

1. 固定 HTML fixture 验证链接、描述、实际语言、排名、stars、forks 和周期增长；覆盖字段缺失与解析异常。
2. 验证总榜 daily / weekly URL 和六个语言榜配置，排除重复榜单。
3. 验证多个榜单引用同一仓库只保留一份元数据，指标分别保留。
4. 验证日期边界、重复运行覆盖、引用一致性，以及抓取失败不覆盖已有 JSON。
5. 用固定时间戳与密钥验证签名；mock 验证无密钥、业务失败、消息限长和敏感信息不进入日志。
6. 验证普通采集不通知，`--notify-only` 不抓取；检查 Actions 事件、权限和归档范围。
7. 如网络可用，使用临时目录进行一次真实采集冒烟检查，不写历史目录、不发送飞书消息。

完成标准：后续运行只产生约定的 JSON；八个榜单完整可读；历史 Markdown 不变；失败不提交半成品；通知可独立验证与重试。真实飞书投递需在配置 Secrets 后验证。

## 8. 已知取舍与参考

- 保留全部快照仍会持续增长。本期通过元数据去重减少重复，不设置未经确认的历史删除或保留期限。
- GitHub 页面结构变化可能使解析失效；用 fixture、空榜校验和失败可见性控制风险，不能保证页面永不变化。
- 这里确认的是本地代码行为，不代表已确认远端 Actions 当前状态或原企微推送来源。

官方参考：

- [GitHub Trending](https://github.com/trending)：总榜、语言与周期筛选入口。
- [飞书自定义机器人](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)：签名、消息格式、长度限制和业务返回码。
- [GitHub Actions Secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets)：敏感配置注入。
- [GitHub Actions Variables](https://docs.github.com/en/actions/concepts/workflows-and-actions/variables)：普通参数配置。
- [Ubuntu 26.04 runner 迁移公告](https://github.blog/changelog/2026-09-17-ubuntu-26-generally-available-and-latest-migration/)：`ubuntu-latest` 的迁移时间与固定旧镜像的方法。
- [Python 发行包清单](https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json)：核对 Python、操作系统和架构组合。
- [setup-python v6](https://github.com/actions/setup-python/blob/v6/README.md)：安装机制、版本配置与 runner 要求。
