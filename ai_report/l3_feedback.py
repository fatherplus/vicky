"""
L3 回写层——使用账本 + 仲裁 + 采纳反馈的来源组装（P2 实现，规格 §6）。

原则：反馈是带证据的陈述，不是分数；采纳是裁决，不是算术。
- 账本 append-only：只在裁决时 UPDATE 状态列；
- 状态机 pending → adopted | rejected，可再裁决（翻案），最新一次生效；
- judged_by 记 human:{标识} / ai:{model}，理由进 note；
- evidence 为空直接拒收——没有真实证据的意见不配进循环。

防环说明（规格 §3）：l2_distill 编译时直接经 store 查 feedbacks 表取 adopted 条目，
不 import 本模块；本模块也不 import l2_distill 的蒸馏逻辑。
judge_pending_with_llm 只复用 l2_distill 的 LLM 网关函数（llm_chat），方向 l3 → l2 合法。
"""

from datetime import datetime, timezone

from . import config
from . import store

# 裁决动词 → 账本状态
VERDICT_MAP = {"adopt": "adopted", "reject": "rejected"}
STATUSES = ("pending", "adopted", "rejected")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ============================================================
# 写回校验与提交
# ============================================================
def find_topic_domain(topic: str, domain: str = "") -> str:
    """topic 必须已存在：knowledge/{domain}/{topic}/overview.md。
    domain 给了就定点查；不给则扫全部 domain 目录。返回实际 domain，不存在返回 ""。"""
    kdir = config.KNOWLEDGE_DIR
    if domain:
        return domain if (kdir / domain / topic / "overview.md").exists() else ""
    if not kdir.exists():
        return ""
    for d in sorted(kdir.iterdir()):
        if d.is_dir() and (d / topic / "overview.md").exists():
            return d.name
    return ""


def submit_feedback(data: dict):
    """POST /api/knowledge/feedback 的业务层。
    返回 (feedback_dict, None) 或 (None, error_str)。错误一律 400 语义。"""
    topic = str(data.get("topic") or "").strip()
    agent = str(data.get("agent") or "").strip()
    evidence = str(data.get("evidence") or "").strip()
    opinion = str(data.get("opinion") or "").strip()
    cited = str(data.get("cited") or "").strip()
    domain = str(data.get("domain") or "").strip()

    if not topic:
        return None, "topic 必填"
    if not agent:
        return None, "agent 必填（自报身份，账本要可追溯）"
    if not evidence:
        return None, "evidence 必填——没有真实证据的意见不进循环"
    if not opinion:
        return None, "opinion 必填"
    if domain and domain not in config.DOMAINS:
        return None, f"domain 非法: {domain}（可选 {sorted(config.DOMAINS)}）"

    found = find_topic_domain(topic, domain)
    if not found:
        return None, f"topic '{topic}' 不存在——先蒸馏出知识主题，再写回使用反馈"
    # domain 给了但与主题实际所在 domain 不符：以主题实际位置为准的前提是别撒谎，直接拒
    if domain and domain != found:
        return None, f"topic '{topic}' 实际在 domain '{found}'，不是 '{domain}'"

    conn = store.get_db()
    try:
        fid = store.insert_feedback(conn, topic=topic, domain=found, agent=agent,
                                    evidence=evidence, opinion=opinion, cited=cited,
                                    created_at=_now())
        conn.commit()
        return store.get_feedback(conn, fid), None
    finally:
        conn.close()


# ============================================================
# 裁决状态机
# ============================================================
def judge_feedback(fid: int, verdict: str, note: str = "", judged_by: str = ""):
    """裁决一条反馈。返回 (feedback_dict, None, 200) 或 (None, error_str, code)。
    状态机：pending → adopted | rejected；可再裁决，最新一次生效（直接覆盖旧裁决）。"""
    status = VERDICT_MAP.get(str(verdict or "").strip().lower())
    if not status:
        return None, "verdict 必须是 adopt 或 reject", 400
    # judged_by 由调用方构造：人工 human:{标识}，AI ai:{model}（规格 §6②）
    if not (judged_by.startswith("human:") or judged_by.startswith("ai:")):
        return None, "judged_by 必须形如 human:{标识} 或 ai:{model}", 400

    conn = store.get_db()
    try:
        if not store.get_feedback(conn, fid):
            return None, f"feedback #{fid} 不存在", 404
        store.set_feedback_verdict(conn, fid, status, judged_by, _now(),
                                   str(note or "").strip())
        conn.commit()
        return store.get_feedback(conn, fid), None, 200
    finally:
        conn.close()


# ============================================================
# 账本查询 / 统计 / 来源组装
# ============================================================
def list_feedbacks_api(topic: str = "", status: str = ""):
    """GET /api/knowledge/feedback。返回 (rows, None) 或 (None, error_str)。"""
    if status and status not in STATUSES:
        return None, f"status 非法: {status}（可选 {list(STATUSES)}）"
    conn = store.get_db()
    try:
        return store.list_feedbacks(conn, topic=topic or None, status=status or None), None
    finally:
        conn.close()


def feedback_stats(topic: str) -> dict:
    """写回次数 + 最近使用（GET /api/knowledge?topic=X 响应用）。"""
    conn = store.get_db()
    try:
        return store.feedback_stats(conn, topic)
    finally:
        conn.close()


def assemble_feedback_sources(topic: str) -> list[dict]:
    """adopted 反馈 → type=feedback 来源列表，与报告来源平级（规格 §6③）。
    注意：l2_distill 编译时直接查 store（防环，规格 §3），此函数供 API/其它消费方。"""
    conn = store.get_db()
    try:
        rows = store.adopted_feedbacks(conn, topic)
    finally:
        conn.close()
    return [{"type": "feedback", "id": r["id"], "agent": r["agent"],
             "cited": r["cited"] or "", "evidence": r["evidence"],
             "opinion": r["opinion"], "note": r["note"] or "",
             "judged_by": r["judged_by"] or ""} for r in rows]


# ============================================================
# AI 批量初裁（cli judge）
# ============================================================
def judge_pending_with_llm() -> dict:
    """LLM 批量初裁全部 pending 反馈（规格 §6②）。
    LLM 拿「反馈全文 + 该主题当前 overview.md」，输出采纳/驳回 + 理由（进 note），
    judged_by = ai:{model}。无 AIMETER_KEY 时优雅跳过。裁决权始终可人工接管（再裁决覆盖）。"""
    # 延迟 import：l3 → l2 方向合法，且避免包 import 期就加载 LLM 配置
    from . import l2_distill as l2

    if not l2.LLM_ON:
        print("⚠️  未设 AIMETER_KEY，跳过 AI 初裁。"
              "人工裁决走 POST /api/knowledge/feedback/{id}/judge")
        return {"skipped": True, "judged": 0, "failed": 0}

    conn = store.get_db()
    try:
        pendings = store.list_feedbacks(conn, status="pending")
    finally:
        conn.close()
    if not pendings:
        print("没有 pending 反馈")
        return {"skipped": False, "judged": 0, "failed": 0}

    judged = failed = 0
    for fb in pendings:
        ov_path = config.KNOWLEDGE_DIR / fb["domain"] / fb["topic"] / "overview.md"
        ov_text = ov_path.read_text(encoding="utf-8") if ov_path.exists() else "（该主题暂无 overview）"
        prompt = (
            f"你是知识库仲裁员。下面是 agent 对知识主题『{fb['topic']}』的一条使用写回反馈，"
            "以及该主题的当前知识内容。请判断反馈是否应采纳：证据真实且能修正/补充知识的采纳；"
            "无据、跑题、误读或情绪化输出的驳回。\n"
            f"【反馈】提交者: {fb['agent']}\n引用: {fb['cited'] or '（未注明）'}\n"
            f"证据: {fb['evidence']}\n意见: {fb['opinion']}\n\n"
            f"【主题当前内容】\n{ov_text}\n\n"
            '只输出一个 JSON 对象：{"verdict": "adopt" 或 "reject", "note": "一句话理由"}')
        raw = l2.llm_chat([{"role": "user", "content": prompt}], max_tokens=400, timeout=120)
        data = l2._parse_json_loose(raw) if raw else None
        verdict = str(data.get("verdict", "")).strip().lower() if isinstance(data, dict) else ""
        verdict = {"adopt": "adopt", "adopted": "adopt",
                   "reject": "reject", "rejected": "reject"}.get(verdict, "")
        if not verdict:
            failed += 1
            print(f"  ! feedback #{fb['id']}：LLM 输出不可解析，保留 pending")
            continue
        note = str(data.get("note", "")).strip() if isinstance(data, dict) else ""
        fb_new, err, _ = judge_feedback(fb["id"], verdict, note=note,
                                        judged_by=f"ai:{l2.DISTILL_MODEL}")
        if err:
            failed += 1
            print(f"  ! feedback #{fb['id']}：{err}")
            continue
        judged += 1
        print(f"  ✓ feedback #{fb['id']} → {fb_new['status']}（{note or '无理由'}）")

    print(f"AI 初裁完成: {judged} 条裁决, {failed} 条失败保留 pending")
    return {"skipped": False, "judged": judged, "failed": failed}
