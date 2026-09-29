# A股买点监控（云端版）

**不用开电脑**。GitHub Actions 定时跑，出买点信号直接微信推送。

---

## 上线状态

定时推送以 GitHub 仓库 `main` 分支的 `.github/workflows/monitor.yml` 和 `outputs/watchlist.json` 为准；本地改文件不会自动部署。发布后到 Actions 核对最新运行时间、结果及仓库清单。工作台的本机清单也不会自动变成云端清单，需按下文配置同步。GitHub Actions 的定时触发可能明显延迟，不适合保证严格每 30 分钟送达；若需准点，应换用可靠的外部定时器触发工作流。

激活后可自查：Actions 页出现「买点监控」工作流即成功。

---

## 手机怎么用

### 加 / 删 / 看（GitHub 手机端或浏览器）

1. 打开仓库 → **Actions** → 左侧选 **买点监控**
2. 右上 **Run workflow**
3. 填参数后点绿色按钮：

| 想做什么 | 怎么填 |
| --- | --- |
| 加一只票 | `add_code` = `600519`，`add_name` = `茅台`（可留空） |
| 删一只票 | `remove_code` = `600519` |
| 只看当前清单和最近信号 | `mode` = `view` |
| 立刻扫一遍并推送 | 什么都不填，直接跑 |

> 建议把仓库 Actions 页加到手机浏览器书签/桌面快捷方式，两下就能开。

### 微信里直接发指令（需先部署 Worker，见下）

在微信 WxPusher 应用里发：

- `加 600519` 或 `加 600519 茅台`
- `删 600519`
- `列表`
- `帮助`

---

## 定时节奏

北京时间（工作流里用 UTC cron 换算）：

- **09:20** 盘前集合竞价扫一次
- **09:30 – 11:00、13:00 – 14:30** 每 30 分钟扫一次；午休及 15:00 后不推送
- GitHub 排队导致任务延迟到停市后时，运行时会再次拦截；正常交易时段每次推送当前清单及买点摘要，无买点也会告知。
- 周末不跑（cron 限定周一至周五）

定时任务每次发送扫描摘要；手动触发仍按信号去重。状态存 `outputs/last_signals.json`，由工作流提交回仓库。

---

## 必需的 Secrets

仓库 **Settings → Secrets and variables → Actions**：

| 名称 | 用途 |
| --- | --- |
| `API_KEY` | 同花顺行情（日线） |
| `ZHITU_TOKEN` | 智兔行情（含分钟线） |
| `WXPUSHER_APP_TOKEN` | 微信推送 |
| `WXPUSHER_UID` | 推送目标用户 |

行情源自动降级：智兔优先（有分钟线）→ 同花顺兜底。

## 电脑工作台同步云端清单

电脑工作台默认仅使用本机 `outputs/watchlist.json`，不应把本机增删误认为微信监控已同步。选择一种方式配置后重启工作台：

- 已在手机 PWA「多设备共享」中使用 GitHub 令牌：把同一枚具备仓库 Contents 读写及 Actions 写权限的令牌设为 Windows 用户环境变量 `MONITOR_GITHUB_TOKEN`。
- 已部署共享代理：设置 `MONITOR_PROXY_URL`（完整 HTTPS 接口地址：Cloudflare Worker 带 `/api`，阿里云 FC 使用函数 HTTP 地址）和 `MONITOR_APP_KEY`（代理的 APP_KEY）。

配置后，读取、添加、删除都会先访问云端；云端失败会报错，不会假装同步成功。勿把令牌或口令写入网页、代码或聊天记录。

---

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `monitor_cloud.py` | 云端入口：解析事件指令、扫描、去重、推送 |
| `monitor_engine.py` | 四周期逐条判定，输出方向（可买入/可卖出/可入场） |
| `formula_eval.py` | 通达信公式求值器（纯标准库） |
| `quote_client.py` | 行情客户端，多源降级 + 成交量单位归一 |
| `push_wxpusher.py` | WxPusher 推送 |
| `model_conditions.py` | 70 张条件卡定义 |
| `models_v5.json` | 30 个策略模型 |
| `outputs/watchlist.json` | 监控清单（持久化） |
| `outputs/last_signals.json` | 已推信号去重键 |
| `cloud/wxpusher_bridge.js` | Cloudflare Worker：微信上行 → 触发工作流 |

**零第三方依赖**，纯 Python 标准库。

---

## 可选：部署微信桥接 Worker

WxPusher 上行消息**只支持回调、没有拉取 API**，所以微信直接发指令需要一个公网端点。Cloudflare Worker 免费额度足够。

```bash
npm i -g wrangler
wrangler login
cd cloud
wrangler secret put GH_TOKEN     # 细粒度 PAT，权限仅本仓库 Actions:write
wrangler deploy
```

再把 `*.workers.dev` 地址填到 WxPusher 应用后台的「上行消息回调 URL」。

---

## 本地调试

```bash
python monitor_cloud.py --mode view
python monitor_cloud.py --mode run --add 600519 --name 茅台 --dry-run
python _smoke_cloud.py          # 离线冒烟，不联网不推送
```
