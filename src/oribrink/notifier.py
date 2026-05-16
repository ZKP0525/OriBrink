"""邮件通知模块。

用 stdlib email.message.EmailMessage（现代 API）+ smtplib；表格直接用
pandas.DataFrame.to_html 渲染，不手拼 HTML 表格。SMTP 失败只记录日志、
不抛出，避免单点失败拖垮整个任务。
"""

from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage

import pandas as pd

from .config import EmailConfig
from .logging import get_logger

log = get_logger("notifier")

_STYLE = """
<style>
body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#222}
h2{border-left:4px solid #c0392b;padding-left:8px;margin:18px 0 8px}
table{border-collapse:collapse;font-size:13px;margin-bottom:12px}
th,td{border:1px solid #ddd;padding:5px 9px;text-align:right}
th{background:#f5f5f5}
td:nth-child(-n+3),th:nth-child(-n+3){text-align:left}
.muted{color:#888;font-size:12px}
</style>
"""


# --------------------------- 格式化小工具 ----------------------------- #
def _cap(v) -> str:
    return f"{v / 1e8:.2f}亿" if isinstance(v, (int, float)) else "-"


def _pct_frac(v) -> str:
    """小数比例 -> 百分比，如 0.0312 -> 3.12%。"""
    return f"{v * 100:.2f}%" if isinstance(v, (int, float)) else "-"


def _pct_val(v) -> str:
    """已是百分比数值，如 9.98 -> 9.98%。"""
    return f"{v:.2f}%" if isinstance(v, (int, float)) else "-"


def _x(v) -> str:
    return f"{v:.2f}倍" if isinstance(v, (int, float)) else "-"


def _num(v) -> str:
    return f"{v:,.0f}" if isinstance(v, (int, float)) else "-"


def _yn(v) -> str:
    return "是" if v else "否"


def _g(v):
    return "-" if v is None or v == "" else v


def _table(records: list[dict]) -> str:
    if not records:
        return '<p class="muted">无</p>'
    return pd.DataFrame(records).to_html(index=False, escape=False, border=0)


def _metrics(t: dict) -> dict:
    try:
        return json.loads(t.get("metrics_json") or "{}")
    except (ValueError, TypeError):
        return {}


# ------------------------- 邮件内容构建 ------------------------------- #
def build_kanglong_email(
    date: str,
    new_kanglong: list[dict],
    snapshot_status: str,
    anomalies: list[str],
) -> tuple[str, str, bool]:
    subject = f"【A股状态提醒】亢龙有悔 - {date}"

    kl_rows = []
    for t in new_kanglong:
        m = _metrics(t)
        kl_rows.append(
            {
                "代码": t["code"], "名称": t["name"],
                "所属行业": _g(m.get("industry")),
                "原连板数": _g(m.get("prev_lianban_count")),
                "今日状态原因": t.get("reason", ""),
                "炸板未回封": _yn(m.get("zhaban_no_refill")),
                "烂板回封": _yn(m.get("lanban_refill")),
                "炸板次数": _g(m.get("break_board_count")),
                "今日成交量": _num(m.get("today_volume")),
                "昨日成交量": _num(m.get("last_volume")),
                "放量倍数": _x(m.get("volume_ratio")),
                "流通市值": _cap(m.get("free_market_cap")),
                "首次封板时间": _g(m.get("first_limit_time")),
                "最后封板时间": _g(m.get("last_limit_time")),
            }
        )

    has_content = bool(kl_rows)
    html = f"""<html><head>{_STYLE}</head><body>
<h2>今日亢龙有悔（{len(kl_rows)}）</h2>{_table(kl_rows)}
<h2>当日快照</h2><p>{snapshot_status}</p>
<h2>异常 / 数据缺失</h2>{_anomaly_html(anomalies)}
<p class="muted">oribrink · {date}</p></body></html>"""
    return subject, html, has_content


def build_qianlong_email(
    date: str,
    new_qianlong: list[dict],
    snapshot_status: str,
    anomalies: list[str],
) -> tuple[str, str, bool]:
    subject = f"【A股竞价提醒】潜龙在渊信号 - {date} 09:25"

    rows, qualified, excellent = [], 0, 0
    for t in new_qianlong:
        m = _metrics(t)
        q = m.get("quality")
        if q == "优质":
            excellent += 1
        elif q == "合格":
            qualified += 1
        rows.append(
            {
                "代码": t["code"], "名称": t["name"],
                "所属行业": _g(m.get("industry")),
                "流通市值": _cap(m.get("free_market_cap")),
                "昨日收盘价": _g(m.get("last_close")),
                "09:25竞价价": _g(m.get("auction_price")),
                "高开幅度": _pct_frac(m.get("gap_open_pct")),
                "昨日成交量": _num(m.get("last_volume")),
                "竞价成交量": _num(m.get("auction_volume")),
                "竞价量占比": _pct_frac(m.get("auction_ratio")),
                "质量评级": _g(q),
                "进入亢龙有悔日期": _g(m.get("prev_state_date")),
            }
        )

    has_content = bool(rows)
    html = f"""<html><head>{_STYLE}</head><body>
<h2>今日新增潜龙在渊（{len(rows)}）｜合格 {qualified}｜优质 {excellent}</h2>
{_table(rows)}
<h2>当日竞价快照</h2><p>{snapshot_status}</p>
<h2>异常 / 数据缺失</h2>{_anomaly_html(anomalies)}
<p class="muted">oribrink · {date} 09:25</p></body></html>"""
    return subject, html, has_content


def _anomaly_html(anomalies: list[str]) -> str:
    if not anomalies:
        return '<p class="muted">无</p>'
    items = "".join(f"<li>{a}</li>" for a in anomalies)
    return f'<ul class="muted">{items}</ul>'


# ----------------------------- 发送 ---------------------------------- #
def send_email(cfg: EmailConfig, subject: str, html: str) -> bool:
    """发送 HTML 邮件。未启用或失败返回 False（不抛出）。"""
    if not cfg.enabled:
        log.info("邮件未启用，跳过发送：%s", subject)
        return False
    if not cfg.recipients:
        log.warning("未配置收件人，跳过发送：%s", subject)
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.sender or cfg.username
    msg["To"] = ", ".join(cfg.recipients)
    msg.set_content("本邮件为 HTML 格式，请使用支持 HTML 的客户端查看。")
    msg.add_alternative(html, subtype="html")

    try:
        if cfg.use_ssl:
            server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30)
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
            server.starttls()
        with server:
            if cfg.username:
                server.login(cfg.username, cfg.password)
            server.send_message(msg)
        log.info("邮件已发送：%s -> %s", subject, cfg.recipients)
        return True
    except Exception as e:  # noqa: BLE001 - 邮件失败不阻断任务
        log.error("邮件发送失败：%s（%s）", subject, e)
        return False
