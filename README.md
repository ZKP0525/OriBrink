# OriBrink

<p align="center">
  <img src="asset/banner.png" alt="OriBrink banner" width="100%">
</p>

OriBrink 是一个 A 股连板状态识别工具。它按交易日计算 **亢龙有悔**，
并在下一交易日集合竞价后判断 **潜龙在渊**，同时把结果保存到 SQLite，
方便命令行查看、历史回测和 WebUI 展示。

状态时序：

```text
T-1 飞龙在天 -> T 亢龙有悔 -> T+1 潜龙在渊
```

## 核心规则

| 状态 | 判断口径 |
|---|---|
| 飞龙在天 | 涨停连板数 ≥ 3 |
| 亢龙有悔 | 昨日曾飞龙在天，今日炸板未回封或烂板回封，且今日成交量 / 昨日成交量 ≥ 1.5 |
| 潜龙在渊 | 昨日曾亢龙有悔，今日集合竞价高开 ≥ 3%，且竞价成交量占昨日成交量达标 |

潜龙竞价量标准：

- 流通市值 < 80 亿：竞价量 / 昨日成交量 > 5% 为合格，> 10% 为优质。
- 流通市值 ≥ 80 亿：竞价量 / 昨日成交量 > 2.5% 为合格。

## 功能

- `ob kanglong`：计算最近交易日亢龙有悔。
- `ob qianlong`：计算最近可用交易日潜龙在渊。
- `ob collect`：采集历史回测必要的 Tushare 原始数据到 JSONL。
- `ob backtest`：只读本地 JSONL，回算历史亢龙/潜龙。
- `ob web`：启动本地 WebUI，按“昨日亢龙 → 今日潜龙 → 失败亢龙 → 今日亢龙”展示结果。
- SQLite 保存结果、空结果、潜龙候选检查和任务记录，避免重复请求。

## 快速开始

如果还没有安装 uv：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

安装依赖：

```bash
uv sync
```

激活虚拟环境：

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1

# Windows cmd
.venv\Scripts\activate.bat
```

复制配置：

```bash
cp config.example.toml config.toml
```

不激活虚拟环境时，也可以把下面的 `ob ...` 写成 `uv run ob ...`。

## 日常命令

```bash
ob kanglong                                # 计算最近交易日亢龙有悔，不发送邮件
ob kanglong --send                         # 计算最近交易日亢龙有悔，并发送邮件
ob kanglong --date 2025-05-15              # 计算指定日期亢龙有悔
ob kanglong --date 2025-05-15 --refresh    # 忽略缓存，重新查询数据源

ob qianlong                                # 计算最近可用交易日潜龙在渊，不发送邮件
ob qianlong --send                         # 计算最近可用交易日潜龙在渊，并发送邮件
ob qianlong --date 2025-05-15              # 查看已缓存日期
ob qianlong --date 2025-05-15 --refresh    # 最近交易日可忽略缓存重算
```

未指定日期时，`kanglong` 和 `qianlong` 都会回退到最近交易日。潜龙使用腾讯
3 秒成交明细，交易日 16:00 后才有当日数据；16:00 前运行会显示上一交易日
的潜龙数据。

## 历史数据与回测

采集最近一年必要原始数据：

```bash
ob collect --from 2025-05-01 --to 2026-05-15
```

回算历史结果：

```bash
ob backtest --from 2025-05-01 --to 2026-05-15
```

`collect` 只采集回测需要的 Tushare 接口与字段：

- `trade_cal`
- `limit_list_d`
- `daily`
- `daily_basic`
- `stk_auction`

原始返回按月拆分为 JSONL，写入 `data/tushare/raw/`。真实 Tushare token 只放
本地 `config.toml`，不要提交。

## WebUI

启动本地看板：

```bash
ob web
```

默认地址：

```text
http://127.0.0.1:8000
```

WebUI 每次请求都会读取 SQLite 最新数据。服务器上每天跑完 `ob kanglong` 和
`ob qianlong` 后，刷新浏览器即可看到新结果，不需要重启 WebUI。

## 配置

核心配置在 `config.toml`：

```toml
[strategy]
min_lianban_count = 3
volume_ratio_threshold = 1.5
gap_open_threshold = 0.03
small_cap_threshold = 8000000000
small_cap_auction_ratio_qualified = 0.05
small_cap_auction_ratio_excellent = 0.10
large_cap_auction_ratio_qualified = 0.025

[storage]
db_path = "data/oribrink.db"
```

邮件配置默认关闭。开启后，亢龙/潜龙任务可发送结果提醒。

## 数据存储

SQLite 负责缓存、快照和审计，不作为候选池判断来源。

| 表 | 作用 |
|---|---|
| `current_stock_state` | 最近状态缓存 |
| `state_transition_history` | 状态流转事件，去重和防重复通知 |
| `daily_state_snapshot` | 每日亢龙/潜龙结果快照 |
| `qianlong_candidate_check` | 潜龙候选检查结果，包括失败原因 |
| `task_run_history` | 任务运行记录，0 条结果也会缓存 |

重跑策略由 `snapshot.overwrite_on_rerun` 控制：

- `false`：已存在快照时写入 `manual` 快照，保留原任务快照。
- `true`：重跑时覆盖任务快照。

## 数据源说明

日常任务主要使用 AkShare 免费数据源：

- 涨停池、昨日涨停池、炸板池：用于筛选飞龙和亢龙弱化形态。
- 历史日 K：只对出现弱化形态的飞龙拉取，用于计算放量倍数。
- 腾讯 3 秒成交明细：用于潜龙竞价判断。

历史回测使用本地 Tushare JSONL，不联网。这样可以在短期购买 Tushare 权限后
一次性缓存必要原始数据，后续反复优化策略。

## 开发

项目结构：

```text
src/oribrink/
├── config.py          配置
├── datasource.py      AkShare 数据标准化
├── strategy.py        纯策略判断
├── storage.py         SQLite 读写
├── tasks.py           亢龙 / 潜龙任务编排
├── tushare_cache.py   Tushare 原始缓存与历史回测
├── webui.py           本地 WebUI
└── cli.py             ob 命令入口
```

运行测试：

```bash
uv run pytest
```

测试全程离线：mock 数据源、不发真实邮件、SQLite 使用内存库。
