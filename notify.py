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

MAX_BODY_BYTES = 20 * 1024
TOP_N = 10
TIMEOUT = (10, 30)
PERIOD_TITLES = {"daily": "总榜日榜", "weekly": "总榜周榜"}


class NotifyError(Exception):
    """通知发送失败（信息已脱敏）。"""


def sign(timestamp, signing_secret):
    """飞书签名：Base64(HMAC-SHA256(key=timestamp\\nsecret, msg=empty))。"""
    key = "{ts}\n{secret}".format(ts=timestamp, secret=signing_secret).encode("utf-8")
    digest = hmac.new(key, b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _entry_lines(entries, repositories):
    lines = []
    for entry in entries:
        repo = repositories[entry["repo_key"]]
        growth = entry.get("stars_in_period")
        suffix = " +{n}".format(n=growth) if growth is not None else ""
        lines.append(
            "{rank}. {name}{suffix}\n{url}".format(
                rank=entry["rank"], name=repo["full_name"], suffix=suffix, url=repo["url"]
            )
        )
    return lines


def build_text(snapshot, repositories, archive_url=None, top_n=TOP_N):
    lines = ["GitHub Trending {date}".format(date=snapshot["date"])]
    for board in snapshot["boards"]:
        if board["language_filter"] != "all":
            continue
        title = PERIOD_TITLES.get(board["period"], board["period"])
        entries = board["entries"][:top_n]
        lines.append("")
        lines.append("【{title} Top {n}】".format(title=title, n=len(entries)))
        lines.extend(_entry_lines(entries, repositories))
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
):
    """构造 text 消息；按 UTF-8 请求体字节数限长，超限逐步减少条目。"""
    for limit in range(top_n, 0, -1):
        payload = {
            "msg_type": "text",
            "content": {
                "text": build_text(snapshot, repositories, archive_url, top_n=limit)
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
    snapshot, repositories, webhook_url=None, signing_secret=None, archive_url=None
):
    if not webhook_url:
        print("未配置 FEISHU_WEBHOOK_URL，跳过飞书通知")
        return False
    payload = build_payload(
        snapshot, repositories, archive_url=archive_url, signing_secret=signing_secret
    )
    send(webhook_url, payload)
    print("飞书通知已发送（{date}）".format(date=snapshot["date"]))
    return True