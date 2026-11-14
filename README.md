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

## 配置

| 配置 | 类型 | 说明 |
| --- | --- | --- |
| `FEISHU_WEBHOOK_URL` | Repository Secret | 飞书机器人 webhook；未配置时跳过通知 |
| `FEISHU_SIGNING_SECRET` | Repository Secret | 飞书机器人签名密钥；机器人启用签名校验后必须配置 |
| `TRENDING_LANGUAGES` | Repository Variable | 可选，逗号分隔语言 slug；默认 `python,javascript,go,html,typescript,java` |

通知内容为总榜日榜 / 周榜 Top 10 与归档链接；语言榜只保存在 JSON 中。
消息按 UTF-8 字节数限制在飞书 20 KB 上限内，超限自动减少条目。

## Actions 行为

- push / pull request：只运行测试，不抓取、不提交、不通知。
- schedule / workflow_dispatch：测试 → 采集 → 仅提交 `data/` → 推送成功后发送飞书通知。
- 验证与归档固定使用 Ubuntu 24.04、Python 3.12。归档只在默认分支运行；手动选择其他分支时只执行验证。
- 通知和提交使用采集步骤输出的快照日期，跨上海时间午夜运行时仍引用本次快照。
- 推送失败时工作流标记失败，不发送成功通知；可用 `--notify-only` 单独重发。

## Special Day

- [2017-03-29](https://github.com/bonfy/github-trending/blob/master/2017/2017-03-29.md) - my repo [qiandao](https://github.com/bonfy/qiandao) record by github-trending(Python)
- [2018-09-27](https://github.com/bonfy/github-trending/blob/master/2018/2018-09-27.md)/[2018-10-09](https://github.com/bonfy/github-trending/blob/master/2018/2018-10-09.md) - my repo [go-mega](https://github.com/bonfy/go-mega) record by github-trending(Go)

## License

MIT
