import json

from oribrink.config import EmailConfig
from oribrink.notifier import build_kanglong_email, build_qianlong_email, send_email


def _trans(code, name, metrics, reason="r"):
    return {"code": code, "name": name, "reason": reason,
            "metrics_json": json.dumps(metrics, ensure_ascii=False)}


def test_build_kanglong_email_has_content_and_tables():
    kl = [_trans("600000", "浦发银行",
                 {"volume_ratio": 1.8, "zhaban_no_refill": True,
                  "free_market_cap": 5e9})]
    subject, html, has = build_kanglong_email("2025-05-15", kl, "已生成", [])
    assert "2025-05-15" in subject
    assert has is True
    assert "浦发银行" in html
    assert "50.00亿" in html  # 5e9 元 = 50 亿


def test_build_kanglong_email_empty():
    subject, html, has = build_kanglong_email("2025-05-15", [], "无", ["接口超时"])
    assert has is False
    assert "接口超时" in html


def test_build_qianlong_email_quality_counts():
    ql = [
        _trans("1", "甲", {"quality": "优质", "gap_open_pct": 0.05,
                            "auction_ratio": 0.12}),
        _trans("2", "乙", {"quality": "合格", "gap_open_pct": 0.04,
                            "auction_ratio": 0.06}),
    ]
    subject, html, has = build_qianlong_email("2025-05-15", ql, "已生成", [])
    assert has is True
    assert "合格 1" in html and "优质 1" in html
    assert "5.00%" in html  # 高开幅度格式化


def test_send_email_disabled_returns_false():
    assert send_email(EmailConfig(enabled=False), "s", "<p>x</p>") is False


def test_send_email_no_recipient_returns_false():
    cfg = EmailConfig(enabled=True, recipients=[])
    assert send_email(cfg, "s", "<p>x</p>") is False
