# OriBrink DB Schema（PostgreSQL）

目标：
1. 能直接落库。
2. 支持盘前选股、回测、复盘三大流程。
3. 支持版本追溯与性能查询。

## 1. 命名与通用约定

1. 使用 `snake_case`。
2. 统一主键：`bigserial id` 或组合唯一键。
3. 统一时间字段：
- `trade_date date`
- `created_at timestamptz`
- `updated_at timestamptz`
4. 金额/比率建议：
- 价格：`numeric(12,4)`
- 比率：`numeric(10,4)` 或 `double precision`

## 2. 建议 Schema

1. `md`：行情与市场数据
2. `ft`：特征数据
3. `st`：策略与信号
4. `bt`：回测
5. `rt`：实盘记录与复盘
6. `sys`：任务、版本与系统元数据

```sql
create schema if not exists md;
create schema if not exists ft;
create schema if not exists st;
create schema if not exists bt;
create schema if not exists rt;
create schema if not exists sys;
```

## 3. 核心表 DDL（可直接执行）

### 3.1 市场基础表

```sql
create table if not exists md.symbol_master (
  id bigserial primary key,
  symbol varchar(16) not null unique,
  exchange varchar(16) not null,
  name varchar(64) not null,
  list_date date,
  delist_date date,
  sector varchar(64),
  is_st boolean default false,
  is_active boolean default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_symbol_master_active on md.symbol_master(is_active);
create index if not exists idx_symbol_master_sector on md.symbol_master(sector);
```

### 3.2 日线行情

```sql
create table if not exists md.symbol_daily (
  id bigserial primary key,
  symbol varchar(16) not null,
  trade_date date not null,
  open numeric(12,4) not null,
  high numeric(12,4) not null,
  low numeric(12,4) not null,
  close numeric(12,4) not null,
  prev_close numeric(12,4),
  volume bigint,
  amount numeric(18,2),
  turnover_rate numeric(10,4),
  adj_factor numeric(16,8),
  is_limit_up boolean,
  is_limit_down boolean,
  data_version varchar(32) not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(symbol, trade_date, data_version)
);

create index if not exists idx_daily_symbol_date on md.symbol_daily(symbol, trade_date desc);
create index if not exists idx_daily_date on md.symbol_daily(trade_date desc);
create index if not exists idx_daily_version on md.symbol_daily(data_version);
```

### 3.3 分钟行情

```sql
create table if not exists md.symbol_intraday (
  id bigserial primary key,
  symbol varchar(16) not null,
  ts timestamptz not null,
  trade_date date not null,
  freq varchar(8) not null default '1m',
  open numeric(12,4) not null,
  high numeric(12,4) not null,
  low numeric(12,4) not null,
  close numeric(12,4) not null,
  volume bigint,
  amount numeric(18,2),
  data_version varchar(32) not null,
  created_at timestamptz not null default now(),
  unique(symbol, ts, freq, data_version)
);

create index if not exists idx_intraday_symbol_ts on md.symbol_intraday(symbol, ts desc);
create index if not exists idx_intraday_trade_date on md.symbol_intraday(trade_date, symbol);
```

### 3.4 竞价快照

```sql
create table if not exists md.auction_snapshot (
  id bigserial primary key,
  symbol varchar(16) not null,
  trade_date date not null,
  auction_change_pct numeric(10,4),
  auction_volume bigint,
  auction_amount numeric(18,2),
  matched_price numeric(12,4),
  unmatched_volume bigint,
  data_version varchar(32) not null,
  created_at timestamptz not null default now(),
  unique(symbol, trade_date, data_version)
);

create index if not exists idx_auction_date on md.auction_snapshot(trade_date desc);
create index if not exists idx_auction_symbol_date on md.auction_snapshot(symbol, trade_date desc);
```

### 3.5 L0 特征（基础行为）

```sql
create table if not exists ft.feature_l0_baseinfo (
  id bigserial primary key,
  symbol varchar(16) not null,
  trade_date date not null,
  auction_change_pct numeric(10,4),
  auction_volume bigint,
  day_high_pct numeric(10,4),
  day_low_pct numeric(10,4),
  day_high_time varchar(8),
  day_low_time varchar(8),
  am_high_pct numeric(10,4),
  am_low_pct numeric(10,4),
  am_high_time varchar(8),
  am_low_time varchar(8),
  is_limit_up boolean,
  is_broken_limit boolean,
  is_weak_limit boolean,
  tail_accumulation_score numeric(10,4),
  turnover_rate numeric(10,4),
  feature_version varchar(32) not null,
  data_version varchar(32) not null,
  created_at timestamptz not null default now(),
  unique(symbol, trade_date, feature_version, data_version)
);

create index if not exists idx_l0_symbol_date on ft.feature_l0_baseinfo(symbol, trade_date desc);
create index if not exists idx_l0_trade_date on ft.feature_l0_baseinfo(trade_date desc);
```

### 3.6 L1 特征（滚动统计）

```sql
create table if not exists ft.feature_l1_market_stats (
  id bigserial primary key,
  symbol varchar(16) not null,
  trade_date date not null,
  window_days int not null default 80,
  limit_up_avg_premium numeric(10,4),
  limit_up_success_rate numeric(10,4),
  next_day_gt5_count int,
  clubbing_count int,
  feature_version varchar(32) not null,
  data_version varchar(32) not null,
  created_at timestamptz not null default now(),
  unique(symbol, trade_date, window_days, feature_version, data_version)
);

create index if not exists idx_l1_symbol_date on ft.feature_l1_market_stats(symbol, trade_date desc);
create index if not exists idx_l1_trade_date on ft.feature_l1_market_stats(trade_date desc);
```

### 3.7 L2 特征（股性/风格）

```sql
create table if not exists ft.feature_l2_behavior_score (
  id bigserial primary key,
  symbol varchar(16) not null,
  trade_date date not null,
  window_days int not null default 80,
  stock_activity_score numeric(10,4),
  recognition_score numeric(10,4),
  rebound_index numeric(10,4),
  style_profit_index numeric(10,4),
  style_loss_index numeric(10,4),
  feature_version varchar(32) not null,
  data_version varchar(32) not null,
  created_at timestamptz not null default now(),
  unique(symbol, trade_date, window_days, feature_version, data_version)
);

create index if not exists idx_l2_symbol_date on ft.feature_l2_behavior_score(symbol, trade_date desc);
create index if not exists idx_l2_trade_date on ft.feature_l2_behavior_score(trade_date desc);
```

### 3.8 策略定义与版本

```sql
create table if not exists st.strategy_definitions (
  id bigserial primary key,
  strategy_key varchar(64) not null unique,
  strategy_name varchar(128) not null,
  description text,
  owner varchar(64),
  status varchar(16) not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists st.strategy_versions (
  id bigserial primary key,
  strategy_key varchar(64) not null,
  version varchar(32) not null,
  params_json jsonb not null,
  code_commit varchar(64),
  feature_version varchar(32),
  is_prod boolean not null default false,
  notes text,
  created_at timestamptz not null default now(),
  unique(strategy_key, version)
);

create index if not exists idx_strategy_versions_key on st.strategy_versions(strategy_key);
create index if not exists idx_strategy_versions_prod on st.strategy_versions(strategy_key, is_prod);
```

### 3.9 信号结果与盘前候选

```sql
create table if not exists st.signal_results (
  id bigserial primary key,
  strategy_key varchar(64) not null,
  strategy_version varchar(32) not null,
  symbol varchar(16) not null,
  trade_date date not null,
  signal_type varchar(16) not null,
  score numeric(10,4),
  reason_tags text[],
  reason_text text,
  data_version varchar(32) not null,
  created_at timestamptz not null default now(),
  unique(strategy_key, strategy_version, symbol, trade_date, signal_type)
);

create index if not exists idx_signal_trade_date on st.signal_results(trade_date desc);
create index if not exists idx_signal_symbol_date on st.signal_results(symbol, trade_date desc);
create index if not exists idx_signal_strategy_date on st.signal_results(strategy_key, trade_date desc);

create table if not exists st.pre_market_candidates (
  id bigserial primary key,
  trade_date date not null,
  symbol varchar(16) not null,
  rank_no int not null,
  total_score numeric(10,4) not null,
  selected_by text[],
  risk_tags text[],
  notes text,
  status varchar(16) not null default 'new',
  created_at timestamptz not null default now(),
  unique(trade_date, symbol)
);

create index if not exists idx_candidates_trade_date_rank on st.pre_market_candidates(trade_date desc, rank_no);
create index if not exists idx_candidates_symbol_date on st.pre_market_candidates(symbol, trade_date desc);
```

### 3.10 回测

```sql
create table if not exists bt.backtest_runs (
  id bigserial primary key,
  run_key varchar(64) not null unique,
  strategy_key varchar(64) not null,
  strategy_version varchar(32) not null,
  start_date date not null,
  end_date date not null,
  config_json jsonb not null,
  status varchar(16) not null default 'running',
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  created_at timestamptz not null default now()
);

create table if not exists bt.backtest_metrics (
  id bigserial primary key,
  run_key varchar(64) not null,
  total_return numeric(12,4),
  annual_return numeric(12,4),
  max_drawdown numeric(12,4),
  sharpe numeric(10,4),
  calmar numeric(10,4),
  win_rate numeric(10,4),
  profit_loss_ratio numeric(10,4),
  trade_count int,
  created_at timestamptz not null default now(),
  unique(run_key)
);

create table if not exists bt.backtest_trades (
  id bigserial primary key,
  run_key varchar(64) not null,
  symbol varchar(16) not null,
  trade_date date not null,
  side varchar(8) not null,
  price numeric(12,4) not null,
  qty int not null,
  amount numeric(18,2),
  fee numeric(12,4),
  reason text,
  created_at timestamptz not null default now()
);

create index if not exists idx_backtest_trades_run on bt.backtest_trades(run_key);
create index if not exists idx_backtest_trades_symbol_date on bt.backtest_trades(symbol, trade_date desc);
```

### 3.11 实盘日志与复盘

```sql
create table if not exists rt.manual_trade_logs (
  id bigserial primary key,
  trade_date date not null,
  symbol varchar(16) not null,
  side varchar(8) not null,
  price numeric(12,4),
  qty int,
  strategy_key varchar(64),
  strategy_version varchar(32),
  matched_pattern boolean,
  decision_reason text,
  result_tag varchar(16),
  pnl_pct numeric(10,4),
  created_by varchar(64),
  created_at timestamptz not null default now()
);

create index if not exists idx_manual_logs_date on rt.manual_trade_logs(trade_date desc);
create index if not exists idx_manual_logs_symbol_date on rt.manual_trade_logs(symbol, trade_date desc);
create index if not exists idx_manual_logs_strategy on rt.manual_trade_logs(strategy_key, trade_date desc);

create table if not exists rt.review_cases (
  id bigserial primary key,
  case_date date not null,
  symbol varchar(16) not null,
  case_type varchar(16) not null,
  title varchar(128),
  summary text,
  tags text[],
  linked_strategy_key varchar(64),
  linked_strategy_version varchar(32),
  action_items text,
  created_at timestamptz not null default now()
);

create index if not exists idx_review_cases_date on rt.review_cases(case_date desc);
create index if not exists idx_review_cases_type on rt.review_cases(case_type);
```

### 3.12 系统任务与快照版本

```sql
create table if not exists sys.job_runs (
  id bigserial primary key,
  job_name varchar(64) not null,
  run_key varchar(64) not null unique,
  status varchar(16) not null,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  duration_ms int,
  error_message text,
  metadata_json jsonb
);

create index if not exists idx_job_runs_name_time on sys.job_runs(job_name, started_at desc);

create table if not exists sys.data_snapshots (
  id bigserial primary key,
  snapshot_date date not null,
  data_version varchar(32) not null,
  feature_version varchar(32) not null,
  is_ready boolean not null default false,
  notes text,
  created_at timestamptz not null default now(),
  unique(snapshot_date, data_version, feature_version)
);

create index if not exists idx_snapshots_date on sys.data_snapshots(snapshot_date desc);
```

## 4. 高频查询建议索引

1. 盘前候选查询
```sql
create index if not exists idx_candidates_date_score on st.pre_market_candidates(trade_date desc, total_score desc);
```

2. 单票历史信号查询
```sql
create index if not exists idx_signal_symbol_strategy_date
on st.signal_results(symbol, strategy_key, trade_date desc);
```

3. 回测结果列表
```sql
create index if not exists idx_backtest_runs_strategy_time
on bt.backtest_runs(strategy_key, started_at desc);
```

## 5. 分区建议（数据增长后启用）

1. `md.symbol_intraday` 按月分区（`trade_date`）。
2. `md.symbol_daily` 按年分区（`trade_date`）。
3. `st.signal_results` 按月分区（`trade_date`）。

## 6. 数据保留策略建议

1. 分钟数据：保留 2~3 年在线，历史归档 Parquet。
2. 信号与回测结果：长期保留（用于策略演化分析）。
3. job 日志：至少保留 180 天。

## 7. 首批落库顺序

1. `md.symbol_master`
2. `md.symbol_daily`
3. `md.auction_snapshot`
4. `ft.feature_l0_baseinfo`
5. `st.strategy_definitions` + `st.strategy_versions`
6. `st.signal_results` + `st.pre_market_candidates`
7. `bt.backtest_runs` + `bt.backtest_metrics` + `bt.backtest_trades`
8. `rt.manual_trade_logs` + `rt.review_cases`
9. `sys.job_runs` + `sys.data_snapshots`
