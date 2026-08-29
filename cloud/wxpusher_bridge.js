// wxpusher_bridge.js —— Cloudflare Worker
// 作用：把你在微信里发给「买点监控」应用的消息，转成 GitHub repository_dispatch，
//       从而触发云端监控工作流（增删监控 / 查看清单），实现「不开电脑、手机直接操作」。
//
// 部署（需 Cloudflare 账号，Workers 免费额度够用，无需绑卡）：
//   1) npm i -g wrangler && wrangler login
//   2) wrangler secret put GH_TOKEN        # 细粒度 PAT，仅授予该仓库 Actions: write
//   3) 在 wrangler.toml 或命令行设置变量：wrangler kv ... 或直接在变量里设 OWNER / REPO
//      （GH_TOKEN 是 secret，OWNER/REPO 是普通变量即可）
//   4) wrangler deploy
//   5) 把部署得到的 *.workers.dev 地址，填到 WxPusher 应用后台的「消息回调地址」
//      （应用设置 → 上行消息回调 URL）。之后在微信里发消息就会打到这个 Worker。
//
// 消息格式（发给应用的内容）：
//   加 600519            或  加 600519 茅台     → 加入监控
//   删 600519            或  移除 600519        → 移除监控
//   列表 / 查看 / 状态    → 推送当前清单与买点
//   帮助                  → 推送指令说明

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("wxpusher bridge ok", { status: 200 });
    }
    let body;
    try {
      body = await request.json();
    } catch {
      return new Response("bad json", { status: 400 });
    }

    const content = String((body && body.data && body.data.content) || "").trim();
    if (!content) return new Response("empty", { status: 200 });

    const cmd = parse(content);

    try {
      const resp = await fetch(
        `https://api.github.com/repos/${env.OWNER}/${env.REPO}/dispatches`,
        {
          method: "POST",
          headers: {
            Authorization: `Bearer ${env.GH_TOKEN}`,
            Accept: "application/vnd.github+json",
            "User-Agent": "wxpusher-bridge",
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ event_type: "monitor-cmd", client_payload: cmd }),
        }
      );
      // 即便 GitHub 侧失败也回 200，避免 WxPusher 反复重试
      return new Response("ok", { status: 200 });
    } catch (e) {
      return new Response("dispatch failed", { status: 200 });
    }
  },
};

function parse(text) {
  const t = text.replace(/^#\d+\s*/, "").replace(/[#＃]/g, "").trim();

  const rm = t.match(/(?:删|移除|取关|remove|unwatch)\s*[:：]?\s*(\d{6})/i);
  if (rm) return { mode: "run", remove_code: rm[1] };

  const ad = t.match(/(?:加|添加|关注|add|watch)\s*[:：]?\s*(\d{6})/i);
  if (ad) {
    const name = t
      .replace(ad[0], "")
      .replace(/(?:加|添加|关注|add|watch)/i, "")
      .replace(/[:：\s#＃]/g, "")
      .trim();
    return { mode: "run", add_code: ad[1], add_name: name };
  }

  if (/列表|查看|清单|状态|list|view|status/i.test(t)) return { mode: "view" };
  if (/帮助|help|命令|菜单/i.test(t)) return { mode: "help" };

  const dig = t.match(/(\d{6})/);
  if (dig) return { mode: "run", add_code: dig[1] };

  return { mode: "help" };
}
