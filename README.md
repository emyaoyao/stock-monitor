# A股买点监控（云端版）

**不用开电脑**。GitHub Actions 定时跑，出买点信号直接微信推送。

---

## ⚠️ 激活前的最后一步

代码和 Secrets 都已就位，但**工作流文件目前放在 `deploy/monitor.yml`**，还没进 `.github/workflows/`，所以定时任务尚未生效。

原因：写入 `.github/workflows/` 需要 token 带 `workflow` 权限，这是 GitHub 的安全门禁，API 侧无法绕过（会返回 404）。

**任选一条激活**：

**A. 网页里把文件挪过去（一步，不用改权限）**

1. 打开 <https://github.com/emyaoyao/stock-monitor/edit/main/deploy/monitor.yml>
2. 把顶部文件名框改成：`../.github/workflows/monitor.yml`
3. 点 **Commit changes**

**B. 给 token 加 `workflow` 权限（以后改工作流更方便）**

GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → 选中那个 token → 勾上 **workflow** → Update token。token 值不变，本地凭据继续可用。

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
- **09:30 – 15:00** 每 30 分钟扫一次
- 周末不跑（cron 限定周一至周五）

只推**新信号**：同一个 `(股票|模型|周期)` 组合出过就不再重复推，避免刷屏。状态存 `outputs/last_signals.json`，由工作流提交回仓库。

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
