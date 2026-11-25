# GitHub Trending(Python)

## 简介

每天采集 GitHub Trending 榜单并归档为结构化 JSON，支持飞书自定义机器人通知。
由 GitHub Actions 定时运行（每天 UTC 02:00，上海时间 10:00），也可手动触发。

历史 Markdown（`2015/`–`2026/` 年份目录）保留不再更新；`analysis.py` 仅适用于旧 Markdown。

## 数据位置

```text
data/
  repos.json                    # 去重后的仓库目录（最新元数据）
  snapshots/
    2026/
      11/
        2026-11-15.json         # 每日快照：各榜单排名与指标
```

- 默认采集 8 个榜单：全语言 daily / weekly 总榜，以及 python、javascript、go、html、typescript、java 的 daily 榜。
- 快照通过 `repo_key`（`owner/name` 小写）引用 `repos.json`；同一天重跑覆盖同一文件。
- 全部榜单抓取并校验成功后才写入；失败不修改已有 JSON。

## 本地运行

```bash
$ git clone https://github.com/bonfy/github-trending.git
$ cd github-trending
$ pip install -r requirements.txt
$ python scraper.py                 # 采集并写入 data/，不发送通知
$ python scraper.py --notify-only   # 不抓取，仅从当天快照发送飞书通知
$ python scraper.py --notify-only --date 2026-11-15   # 重发指定日期的快照
$ python -m unittest discover -s tests -t .   # 运行测试
```

可选参数 `--data-dir <目录>` 指定数据目录（默认 `data`）。本地运行只生成数据，Git 提交由 Actions 完成。

## 历史 Markdown 提取与归档

```bash
python3 archive_history.py
# 自定义输入根目录和输出根目录
python3 archive_history.py --source-dir /path/to/github-trending --data-dir /path/to/data
```

仅使用 Python 标准库，扫描 `YYYY/YYYY-MM-DD.md`，将结果写入 `data/history/`：
`repos.json` 为去重仓库目录，`snapshots/YYYY/MM/YYYY-MM-DD.json` 为逐日榜单，
`manifest.json` 为数量与日期范围汇总。原 Markdown 和现有在线采集 JSON 保留。
重复运行覆盖同名归档，结果一致；不会清理输入中已不存在的旧快照。

历史条目保留显示名称、URL、多行简介、排名和来源行号，快照附源文件路径与 SHA256。
stars、forks、增长数、实际语言和抓取时间无法从历史文件恢复，保存为 `null`；
语言标题仅作为榜单筛选条件。历史榜内重复记录保留，避免丢失原始观察。

原始 Markdown 可运行 `python3 archive_markdown.py` 按年份压缩到
`data/history/markdown/YYYY.zip`，保留原文件，不核对内容哈希。

## 配置

| 配置 | 类型 | 说明 |
| --- | --- | --- |
| `FEISHU_WEBHOOK_URL` | Repository Secret | 飞书机器人 webhook；未配置时跳过通知 |
| `FEISHU_SIGNING_SECRET` | Repository Secret | 飞书机器人签名密钥；机器人启用签名校验后必须配置 |
| `TRENDING_LANGUAGES` | Repository Variable | 可选，逗号分隔语言 slug；默认 `python,javascript,go,html,typescript,java` |

通知为最多 8 个去重项目的每日精选，附关注理由、简介、语言、日增 / 周增和归档链接：

- **首次发现**：首次进入 JSON 记录的项目；首日只建立基线，不标为新增。回归项目不重复标新。
- **日增 Top 3**：所有已采集日榜按周期新增 star 排序；同仓库优先使用总榜数值，跨榜不累加。
- **持续上榜**：最近 7 个自然日内至少 3 天出现在已采集日榜，同时展示当前连续上榜天数；满窗口显示“至少 7 天”。
- **周增 Top 3**：周榜新增 star 独立排序，不与日增或其他日期周增相加。

各类信号轮流选入摘要，同一项目合并理由。历史不足会注明快照天数，缺失日期不代表零增长；首次发现不代表仓库刚创建。
分析只使用目标日及此前 JSON，支持指定日期重发；增长加速分析暂未启用。旧 `analysis.py` 继续仅分析历史 Markdown。
消息按 UTF-8 字节数限制在飞书 20 KB 上限内，超限自动减少条目。

## Actions 行为

- push / pull request：只运行测试，不抓取、不提交、不通知。
- schedule / workflow_dispatch：测试 → 采集 → 仅提交 `data/` → 推送成功后发送飞书通知。
- 验证与归档固定使用 Ubuntu 24.04、Python 3.12。归档只在默认分支运行；手动选择其他分支时只执行验证。
- 通知和提交使用采集步骤输出的快照日期，跨上海时间午夜运行时仍引用本次快照。
- 推送失败时工作流标记失败，不发送成功通知；可用 `--notify-only` 单独重发。

## 黄金观察提醒

独立的 **Feishu Gold Observation Reminder** 工作流在周一至周五北京时间 09:30、15:00、21:00 发送飞书卡片，包含伦敦金报价、较上次有效报价的涨跌和固定锚点参考汇率。工作流复用上述飞书密钥，需要配置签名密钥。合入默认分支后，可在 Actions 中选择 `test` 手动发送测试卡片，测试不会更新报价基准。

[黄金观察提醒配置与报价说明](docs/02-solution/feishu-gold-reminder.md)

## Special Day

- [2017-03-29](https://github.com/bonfy/github-trending/blob/master/2017/2017-03-29.md) - my repo [qiandao](https://github.com/bonfy/qiandao) record by github-trending(Python)
- [2018-09-27](https://github.com/bonfy/github-trending/blob/master/2018/2018-09-27.md)/[2018-10-09](https://github.com/bonfy/github-trending/blob/master/2018/2018-10-09.md) - my repo [go-mega](https://github.com/bonfy/go-mega) record by github-trending(Go)

## License

MIT
