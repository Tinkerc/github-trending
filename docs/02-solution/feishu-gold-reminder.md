# 飞书黄金小时播报方案

## 目标与范围

通过独立的 GitHub Actions 工作流每小时发送一条通用金价卡片，沿用 Trending 通知的仓库密钥。卡片展示伦敦金美元报价、推算人民币金价、较上次有效报价的涨跌和固定锚点参考汇率，并提供上金所 Au99.99 延时行情链接。

## 调度与接口

工作流 `.github/workflows/feishu-reminder.yml` 使用 `17 * * * *`，每天在北京时间每小时第 17 分钟触发，含周末。定时运行统一以 `--slot hourly` 调用 `feishu_reminder.py`。手动运行可选 `hourly` 立即播报，默认选 `test` 发送带测试标记的卡片。发送脚本使用 Python 标准库，通过 `FEISHU_WEBHOOK_URL` 和 `FEISHU_SIGNING_SECRET` 获取凭据，按飞书自定义机器人的签名方式发送。

全天计划触发 24 次。避开整点可减少高峰期的调度延迟。每次触发尝试发送一条卡片，报价过期或行情不可用时在卡片中标明。[GitHub 调度说明](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows#scheduled-workflows-running-at-unexpected-times)

## 行情与历史比较

- 每次发送前查询免密钥接口 `GET https://api.gold-api.com/price/XAU`，读取美元每金衡盎司报价和采集时间 `updatedAt`。请求超时为 8 秒，卡片显示北京时间。
- 使用最近一条有效的 XAU/USD 快照作为基准。差价为本次价格减上次价格，涨跌幅为差价除以上次价格再乘 100%。卡片同时显示基准价格和采集时间。首次采集只建立基准。
- 定时运行与手动 `hourly` 将有效的新报价保存为 `quote.json`，记录 `symbol`、`currency`、十进制价格字符串 `price` 和 UTC 采集时间 `updatedAt`。工作流用原生 GitHub 令牌恢复同一分支最新的 `feishu-gold-xau-quote` 文件产物。同分支正式播报按队列串行执行。文件产物使用仓库的保留期，每个运行保留一份快照。手动 `test` 可读基准并预览比较结果。
- 恢复步骤先根据运行时的 `RUNNER_TEMP` 确定快照目录，并经 `GITHUB_ENV` 传给发送和归档步骤。目录在调用 GitHub API 之前设置，以便读取历史失败时仍可保存新报价。GitHub 在作业级 `env` 中无法解析 `runner.temp`，验证时检查工作流表达式作用域和三个步骤的路径一致性。[GitHub Actions 上下文](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#context-availability) · [跨步骤环境变量](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands#setting-an-environment-variable)
- 报价已超过 5 分钟、采集时间重复或倒退时，保留上次有效快照并跳过涨跌计算。行情接口或基准读取失败时继续发送卡片。新报价在尝试发送飞书前落盘，即使飞书发送失败也能保留这条采集记录。

## 固定锚点参考汇率

按伦敦金 3544 美元/金衡盎司、Au99.99 763 元/克和每金衡盎司 31.1034768 克，计算 `763 × 31.1034768 ÷ 3544 ≈ 6.6964` 元/美元。卡片每次都显示这组固定锚点及其隐含换算率。该数值包含两个市场的价差，只作金价口径换算参考。

## 启用与验证

1. 工作流复用 Trending 通知的仓库 Secret。需要补充配置时，在 **Settings → Secrets and variables → Actions** 设置以下两项，并在飞书群自定义机器人的安全设置中开启签名校验。
   - `FEISHU_WEBHOOK_URL` 填飞书机器人的完整 webhook 地址。
   - `FEISHU_SIGNING_SECRET` 填机器人签名密钥。
2. 将工作流合入仓库默认分支 `master`。在 **Actions → Feishu Gold Price Broadcast → Run workflow** 选择 `test`，确认群中收到测试卡片。选择 `hourly` 或等定时运行后，可在该次运行页面下载 `feishu-gold-xau-quote` 文件产物。
3. 若原 Mac 任务继续向同群发送飞书提醒，两个任务会分别发卡片。飞书请求超时后，先查看群记录，再决定是否手动重跑。

本地可通过 `python3 feishu_reminder.py --slot hourly --dry-run` 离线预览卡片。验证工作流的 cron、定时入口和手动选项，并运行仓库的 unittest 测试，覆盖播报卡片、初次落盘、连续采集涨跌、过期与重复报价、固定参考汇率及手动测试对基准的影响。

数据与单位出处见 [Gold API 说明](https://gold-api.com/faqs)、[NIST 贵金属单位换算](https://www.nist.gov/pml/owm/metric-si/unit-conversion/precious-metals-conversion-information)和[上金所 Au99.99 合约](https://www.sge.com.cn/cpfw/Product_service_details?cplx=7&parent_cplx=0&pro_id=793730879941324800)。运行配置见 [GitHub Actions 调度规则](https://docs.github.com/zh/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)、[文件产物接口](https://docs.github.com/en/rest/actions/artifacts)和[飞书自定义机器人使用指南](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)。
