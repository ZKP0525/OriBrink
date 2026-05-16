# oribrink

A 股连板状态识别与邮件提醒系统。基于 AkShare 数据源，在收盘后识别
“亢龙有悔”，在次日集合竞价后识别“潜龙在渊”。数据库只作为缓存、快照、
去重通知和任务审计，不作为候选池判断来源。

状态时序：**T-1 飞龙在天 → T 亢龙有悔 → T+1 潜龙在渊**

- **飞龙在天**：连板数 ≥ 3 的涨停个股。
- **亢龙有悔**：曾飞龙在天，出现炸板未回封或烂板回封并放量。
- **潜龙在渊**：曾亢龙有悔，集合竞价高开 ≥3% 且竞价爆量。
  - 高开幅度大于等于 3%；
  - 若流通市值小于 80 亿，竞价成交量 / 昨日成交量大于 5% 为合格，大于 10% 为优质；
  - 若流通市值大于等于 80 亿，竞价成交量 / 昨日成交量大于 2.5% 为合格。

## 技术栈

现代轻量工具链：[uv](https://docs.astral.sh/uv/) 管理依赖、`typer` 命令行、
`rich` 输出与日志、`pydantic` 类型化配置、`pandas` 数据处理、stdlib `sqlite3`
存储、stdlib `smtplib` 发信、`pytest` 测试。

## 安装

如果还没有安装 uv：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

安装项目依赖：

```bash
uv sync
```

## 激活环境

macOS / Linux：

```bash
source .venv/bin/activate
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
```

Windows cmd：

```bat
.venv\Scripts\activate.bat
```

不激活虚拟环境时，也可以把下面的 `ob ...` 命令写成 `uv run ob ...`。

## 配置

```bash
cp config.example.toml config.toml   # 修改阈值、SMTP、收件人
```

## 命令

```bash
ob kanglong                                # 默认计算最近交易日亢龙有悔
ob kanglong --no-send                      # 默认跑最近交易日，不发送邮件
ob kanglong --date 2025-05-15              # 计算指定日期亢龙有悔
ob kanglong --date 2025-05-15 --refresh    # 忽略缓存，重新查询数据源

ob qianlong                                # 默认计算最近交易日潜龙在渊
ob qianlong --no-send                      # 默认跑最近交易日潜龙在渊
ob qianlong --date 2025-05-15              # 查看已缓存日期；未缓存历史日期暂不回算
ob qianlong --date 2025-05-15 --refresh    # 忽略缓存，重新查询数据源

ob collect --from 2025-05-01 --to 2026-05-15   # 采集必要 Tushare 原始数据到 JSONL
ob backtest --from 2025-05-01 --to 2026-05-15  # 只读本地 JSONL，回算历史亢龙/潜龙
ob web                                           # 打开本地 WebUI 查看已保存数据
```

非交易日（涨停股池为空）会自动跳过并记入 `task_run_history`。

### 状态时序

- `ob kanglong --date T` 先从 T 日的“昨日涨停池”中按连板数筛出
  T-1 的飞龙候选，再结合 T 日涨停池、炸板池和成交量判断 T 日亢龙。
- `ob kanglong` 和 `ob qianlong` 未指定日期时都会先回退到最近交易日。
- 两个命令默认优先读 SQLite 缓存；0 条结果也会通过任务运行记录缓存，避免
  重复请求数据源。需要重算时使用 `--refresh`。
- 潜龙使用腾讯 3 秒成交明细，交易日 16:00 后才有当日数据；16:00 前运行会
  显示上一交易日的潜龙数据。
- `ob qianlong --date T` 支持查看已缓存日期；未缓存历史日期暂不回算，只支持
  最近交易日实时计算。
- `ob collect` 只采集历史回测必要的 Tushare 接口与字段：
  `trade_cal`、`limit_list_d`、`daily`、`daily_basic`、`stk_auction`。
  原始返回按月拆分为 JSONL 写入 `data/tushare/raw/`，可提交到 Git；真实 token
  只放本地 `config.toml`。
- `ob backtest` 不联网，只读本地 Tushare JSONL，生成历史亢龙/潜龙快照与
  0 条任务记录，方便后续调整策略后重复回算。
- `ob web` 读取 SQLite 快照、潜龙候选检查和任务记录，按“昨日亢龙 → 今日
  潜龙 → 进化失败的亢龙 → 今日亢龙”的链路展示结果，默认地址是
  `http://127.0.0.1:8000`。

## 数据存储

SQLite，四张表（PRD 第 7 节）：

| 表 | 作用 |
|---|---|
| `current_stock_state` | 最近状态缓存，不参与候选池判断 |
| `state_transition_history` | 状态流转事件，去重 + 防重复通知 |
| `daily_state_snapshot` | 每日任务结果快照 |
| `task_run_history` | 任务运行记录，判断数据可靠性 |

重跑策略由 `snapshot.overwrite_on_rerun` 控制：`false` 时已存在快照改写为
`manual` 类型，保留原任务快照；`true` 时覆盖。

## 模块结构

```
src/oribrink/
├── config.py      配置（pydantic + tomllib）
├── logging.py     日志（rich handler）
├── models.py      领域模型与状态常量
├── datasource.py  AkShare 深模块：标准化字段/时间/日期、异常隔离
├── strategy.py    纯策略：三状态识别（可离线单测）
├── storage.py     SQLite 读写
├── snapshot.py    每日状态快照生成
├── query.py       快照查询工具函数（CLI 不暴露）
├── notifier.py    邮件构建（pandas→HTML）与发送
├── tasks.py       亢龙 / 潜龙任务编排
└── cli.py         ob 命令行入口
```

## 测试

```bash
uv run pytest
```

测试全程离线：mock 数据源、不发真实邮件、SQLite 用内存库，覆盖字段标准化、
三状态识别边界、存储去重、快照重跑、邮件渲染与端到端任务流转。

## 数据源稳定性

AkShare 的 `stock_zh_a_hist` 在循环里被快速调用时容易被 eastmoney 限流
（`RemoteDisconnected`）。系统据此优化：

- **按需取数**：放量（今日量/昨日量）只是炸板未回封或烂板回封*之后*的二次闸门，
  这些弱化形态都能从已抓取的涨停/炸板池零网络判断。所以历史日 K **只对出现
  弱化形态的飞龙拉取**，没有弱化形态的交易日完全不发逐股请求。
- **日 K 双数据源**：东财 `stock_zh_a_hist`（push2his）被限流时自动回退腾讯
  `stock_zh_a_hist_tx`。东财成交量与腾讯日 K、腾讯成交明细均按手处理，使放量
  倍数与竞价量占比口径一致。
- **节流 + 重试**：逐股请求间隔 + 有限重试，均在 `[datasource]` 配置：

  ```toml
  [datasource]
  retry_attempts = 4
  retry_backoff = 1.0
  request_interval = 0.5   # 调大更稳但更慢
  ```

  中间重试以 DEBUG 记录（默认不刷屏），仅最终失败计入当日 anomalies，
  单股失败不阻断整批。

## 设计要点

- `datasource` 是深模块：用简单接口隐藏 AkShare 字段差异、时间格式
  （`092500`/`09:25:00`/`141354`）、空数据与接口异常。
- `strategy` 不依赖 AkShare / 数据库 / 邮件，纯函数便于重点测试。
- 单只股票异常不阻断整批；关键数据缺失不做状态升级；不静默失败。
- 任务候选池来自指定日期的数据源，绝不通过当前状态反推某日状态池。
