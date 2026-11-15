# coding: utf-8
"""飞书自定义机器人通知：消息构造、签名、发送与业务响应检查。

日志与异常信息不包含 webhook URL 或签名密钥。
"""

import base64
import hashlib
import hmac
import json
import time

import requests

import trends

MAX_BODY_BYTES = 20 * 1024
TOP_N = trends.TOP_N
TIMEOUT = (10, 30)


class NotifyError(Exception):
    """通知发送失败（信息已脱敏）。"""


def sign(timestamp, signing_secret):
    """飞书签名：Base64(HMAC-SHA256(key=timestamp\\nsecret, msg=empty))。"""
    key = "{ts}\n{secret}".format(ts=timestamp, secret=signing_secret).encode("utf-8")
    digest = hmac.new(key, b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def build_text(snapshot, repositories, archive_url=None, top_n=TOP_N, digest=None):
    digest = digest if digest is not None else trends.build_digest(snapshot, repositories)
    lines = ["GitHub Trending {date} 今日精选".format(date=snapshot["date"])]
    if digest["is_baseline"]:
        lines.append("首次采集基线，暂不标记首次发现。")
    else:
        lines.append("今日首次发现 {n} 个项目。".format(n=digest["new_count"]))
    lines.append("近 7 天有 {n} 天快照；仅统计已采集榜单，缺失日不代表零增长。".format(
        n=digest["observed_days"]
    ))
    if not digest["items"]:
        lines.append("今日暂无符合条件的精选项目。")
    for index, item in enumerate(digest["items"][:top_n], start=1):
        repo = repositories[item["repo_key"]]
        lines.extend(["", "{n}. {name}【{reasons}】".format(
            n=index, name=repo["full_name"], reasons=" / ".join(item["reasons"])
        )])
        metrics = []
        for field, label in (("daily_stars", "日增"), ("weekly_stars", "周增")):
            if item[field] is not None:
                metrics.append("{label} +{n:,} ⭐".format(label=label, n=item[field]))
        if item["days_seen"] >= 3:
            metrics.append("近 7 天日榜出现 {n} 天，当前连续{prefix} {streak} 天".format(
                n=item["days_seen"], streak=item["streak"],
                prefix="至少" if item["streak"] == 7 else "",
            ))
        if repo.get("language"):
            metrics.append(repo["language"])
        if metrics:
            lines.append(" · ".join(metrics))
        description = " ".join(repo.get("description", "").split())
        if description:
            lines.append(description[:160])
        lines.append(repo["url"])
    if archive_url:
        lines.append("")
        lines.append("归档: {url}".format(url=archive_url))
    return "\n".join(lines)


def _serialize(payload):
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def build_payload(
    snapshot,
    repositories,
    archive_url=None,
    signing_secret=None,
    timestamp=None,
    top_n=TOP_N,
    digest=None,
):
    """构造 text 消息；按 UTF-8 请求体字节数限长，超限逐步减少条目。"""
    for limit in range(top_n, 0, -1):
        payload = {
            "msg_type": "text",
            "content": {
                "text": build_text(snapshot, repositories, archive_url, top_n=limit, digest=digest)
            },
        }
        if signing_secret:
            ts = str(int(time.time())) if timestamp is None else str(timestamp)
            payload["timestamp"] = ts
            payload["sign"] = sign(ts, signing_secret)
        if len(_serialize(payload)) < MAX_BODY_BYTES:
            return payload
    raise NotifyError("消息超出长度限制，无法缩减到允许范围")


def send(webhook_url, payload):
    body = _serialize(payload)
    try:
        response = requests.post(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        result = response.json()
    except requests.RequestException as exc:
        # 异常字符串可能携带完整 webhook URL，只记录异常类型。
        raise NotifyError("飞书请求失败: {t}".format(t=type(exc).__name__)) from None
    except ValueError:
        raise NotifyError("飞书响应不是有效 JSON") from None
    if result.get("code") != 0:
        raise NotifyError(
            "飞书业务失败 code={code} msg={msg}".format(
                code=result.get("code"), msg=result.get("msg", "")
            )
        )


def send_notification(
    snapshot, repositories, webhook_url=None, signing_secret=None, archive_url=None,
    digest=None,
):
    if not webhook_url:
        print("未配置 FEISHU_WEBHOOK_URL，跳过飞书通知")
        return False
    payload = build_payload(
        snapshot, repositories, archive_url=archive_url, signing_secret=signing_secret,
        digest=digest,
    )
    send(webhook_url, payload)
    print("飞书通知已发送（{date}）".format(date=snapshot["date"]))
    return True
