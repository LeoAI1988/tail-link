"""
匹配算法 - 双引擎
  1. 人脉/对象匹配 (DATING/TALENT): 基于多维特征加权评分
  2. 资源/项目匹配 (RESOURCE/PROJECT): 基于供需双向匹配

设计原则:
  - 不调外部 LLM (节省成本, 离线可跑)
  - 评分透明, 每项可解释
  - 推演基于规则 (用户后续可换成 LLM 增强)
"""
from typing import List, Tuple, Dict, Any
from datetime import datetime, timedelta
from models import Need, Owner, NeedType, Match
import json


# ===== 通用工具 =====

def _safe_get(d: dict, key: str, default=None):
    return d.get(key, default) if isinstance(d, dict) else default


def _range_overlap(a: List[int], b: List[int]) -> float:
    """两个区间 [min, max] 的重叠度, 返回 0-1"""
    if not a or not b or len(a) < 2 or len(b) < 2:
        return 0.5  # 没声明偏好, 中性
    lo = max(a[0], b[0])
    hi = min(a[1], b[1])
    if hi < lo:
        return 0.0
    span_a = a[1] - a[0] if a[1] > a[0] else 1
    span_b = b[1] - b[0] if b[1] > b[0] else 1
    return (hi - lo) / max(span_a, span_b)


def _jaccard(a: List[str], b: List[str]) -> float:
    """集合 Jaccard 相似度"""
    a, b = set(a or []), set(b or [])
    if not a and not b:
        return 0.5
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _mbti_compat(a: str, b: str) -> float:
    """MBTI 简版兼容 (基于 4 维)
    E/I + N/S + T/F + J/P - 维度相同=高分, 一维互补=中分, 冲突=低分
    """
    if not a or not b or len(a) < 4 or len(b) < 4:
        return 0.5
    same = sum(1 for i in range(4) if a[i] == b[i])
    return same / 4


# ===== 1. 对象/找人匹配 (DATING / TALENT) =====

def score_dating(need: Need, owner_a: Owner, target: Owner) -> Dict[str, Any]:
    """给一个需求 vs 候选主人打分, 返回 {total, breakdown, rationale}"""
    spec = need.spec or {}
    pref = owner_a.dating_pref or {}

    # 年龄匹配: target.age 必须在 [lo, hi] 区间
    score_age = 0.5  # 默认中性
    if target.age and (spec.get("age_range") or pref.get("age_range")):
        age_range = spec.get("age_range") or pref.get("age_range")
        if len(age_range) >= 2:
            lo, hi = age_range[0], age_range[1]
            if lo <= target.age <= hi:
                # 在区间内, 按距中位数距离打分
                mid = (lo + hi) / 2
                span = max(hi - lo, 1)
                dist = abs(target.age - mid) / span
                score_age = max(0.5, 1.0 - dist * 0.5)
            else:
                # 在区间外, 按超出距离减分
                dist = min(abs(target.age - lo), abs(target.age - hi))
                score_age = max(0.0, 0.5 - dist * 0.1)

    score_gender = 1.0
    g_pref = spec.get("gender_pref") or pref.get("gender_pref")
    if g_pref and target.gender and g_pref != target.gender and g_pref != "any":
        score_gender = 0.0

    score_city = 0.0
    c_pref = spec.get("city_pref") or pref.get("city_pref") or []
    if not c_pref or target.city in c_pref:
        score_city = 1.0
    elif any(c in (target.city or "") for c in c_pref):
        score_city = 0.6

    # 性格 (MBTI 兼容 + 兴趣重合)
    p_a = owner_a.personality or {}
    p_b = target.personality or {}
    score_mbti = _mbti_compat(_safe_get(p_a, "mbti"), _safe_get(p_b, "mbti"))
    score_interest = _jaccard(p_a.get("interests", []), p_b.get("interests", []))

    # 价值观 (must_have 命中)
    must = spec.get("must_have") or pref.get("must_have") or []
    nice = spec.get("nice_to_have") or pref.get("nice_to_have") or []
    target_traits = p_b.get("traits", []) + p_b.get("values", [])
    must_hit = _jaccard(must, target_traits)
    nice_hit = _jaccard(nice, target_traits)

    # 收入/家境 (找对象场景下不卡太死, 用 soft 评分)
    f_a = owner_a.family or {}
    f_b = target.family or {}
    score_income = 0.7  # 默认中性
    if f_a.get("income_band") and f_b.get("income_band"):
        # 同档 = 1.0, 差一档 = 0.5, 差两档 = 0.2
        try:
            diff = abs(int(f_a["income_band"]) - int(f_b["income_band"]))
            score_income = max(0.2, 1.0 - diff * 0.4)
        except (ValueError, TypeError):
            score_income = 0.7

    # 排除项
    deal_breaker = spec.get("deal_breaker") or []
    if any(t.lower() in (target_traits + [target.city or ""]).__str__().lower()
           for t in deal_breaker):
        return {"total": 0, "breakdown": {}, "rationale": f"触发排除项: {deal_breaker}"}

    weights = {
        "age": 0.15, "gender": 0.10, "city": 0.10,
        "mbti": 0.10, "interest": 0.20, "must_have": 0.20,
        "nice_to_have": 0.05, "income": 0.10
    }
    breakdown = {
        "年龄匹配": round(score_age * 100, 1),
        "性别匹配": round(score_gender * 100, 1),
        "城市匹配": round(score_city * 100, 1),
        "MBTI 兼容": round(score_mbti * 100, 1),
        "兴趣重合": round(score_interest * 100, 1),
        "必须条件": round(must_hit * 100, 1),
        "加分条件": round(nice_hit * 100, 1),
        "家境接近": round(score_income * 100, 1),
    }
    weighted = (
        score_age * weights["age"] +
        score_gender * weights["gender"] +
        score_city * weights["city"] +
        score_mbti * weights["mbti"] +
        score_interest * weights["interest"] +
        must_hit * weights["must_have"] +
        nice_hit * weights["nice_to_have"] +
        score_income * weights["income"]
    )
    total = round(weighted * 100, 1)

    rationale = (
        f"兴趣重合度 {int(score_interest*100)}%, "
        f"必须条件命中 {int(must_hit*100)}%, "
        f"MBTI 兼容度 {int(score_mbti*100)}%"
    )
    return {"total": total, "breakdown": breakdown, "rationale": rationale}


# ===== 2. 资源/项目匹配 (RESOURCE / PROJECT) =====

def score_resource(need: Need, owner_a: Owner, target: Owner) -> Dict[str, Any]:
    """供需匹配: 甲方要 X, 乙方能提供 X → 高分"""
    spec = need.spec or {}
    target_res = target.resources or {}

    # 类目重合
    score_category = _jaccard(
        [spec.get("category", "")],
        target_res.get("offer_categories", [])
    )

    # 行业重合
    score_industry = _jaccard(
        [spec.get("industry", "")],
        [target_res.get("industry", "")]
    )

    # 供给/需求
    score_offer = _jaccard(
        spec.get("requirements", []),
        target_res.get("can_offer", [])
    )

    # 互补性 (甲方 looking_for 命中乙方 can_offer)
    a_res = owner_a.resources or {}
    score_need = _jaccard(
        a_res.get("looking_for", []),
        target_res.get("can_offer", [])
    )

    # 预算/规模匹配 (取对数级别比较)
    score_budget = 0.5
    if spec.get("budget_band") and target_res.get("deal_size_band"):
        try:
            diff = abs(int(spec["budget_band"]) - int(target_res["deal_size_band"]))
            score_budget = max(0.0, 1.0 - diff * 0.3)
        except (ValueError, TypeError):
            score_budget = 0.5

    weights = {"类目匹配": 0.20, "行业匹配": 0.15, "供给能力": 0.30, "需求命中": 0.25, "规模匹配": 0.10}
    breakdown = {
        "类目匹配": round(score_category * 100, 1),
        "行业匹配": round(score_industry * 100, 1),
        "供给能力": round(score_offer * 100, 1),
        "需求命中": round(score_need * 100, 1),
        "规模匹配": round(score_budget * 100, 1),
    }
    weighted = sum(breakdown[k] / 100 * w for k, w in weights.items())
    total = round(weighted, 1)

    rationale = (
        f"供给能力 {int(score_offer*100)}%, "
        f"需求命中 {int(score_need*100)}%, "
        f"类目 {int(score_category*100)}%"
    )
    return {"total": total, "breakdown": breakdown, "rationale": rationale}


# ===== 推演生成 (规则版, 不调 LLM) =====

def _need_type_is(need, *types):
    """NeedType 比对, 兼容 enum 和字符串"""
    nt = need.need_type
    if hasattr(nt, 'value'):
        nt = nt.value
    return str(nt) in [t.value if hasattr(t, 'value') else str(t) for t in types]


def _generate_predictions(score: float, need: Need, owner_a: Owner, target: Owner) -> List[str]:
    """基于分数生成推演场景"""
    if _need_type_is(need, NeedType.DATING, NeedType.TALENT):
        if score >= 80:
            return [
                f"首次线下见面建议: 共同兴趣活动 (避免正式相亲场合)",
                f"3 个月内关系发展可能: 朋友 → 暧昧 → 恋人 (基于 MBTI 兼容)",
                f"潜在摩擦点: {_safe_get(target.personality, 'mbti', '未知')} 性格与 {(_safe_get(owner_a.personality, 'mbti', '未知'))} 可能在计划性上有冲突"
            ]
        elif score >= 60:
            return [
                "建议先做朋友, 3-6 个月观察",
                "若共同点 60% 以上, 可尝试深度交流"
            ]
        else:
            return ["匹配度偏低, 建议保持社交距离"]
    else:  # RESOURCE / PROJECT
        if score >= 70:
            return [
                f"建议首轮沟通: 验证 {target.agent.owner_name} 的实际供给能力",
                "3 周内可推进小规模试单",
                "潜在风险: 需先做对方背调"
            ]
        else:
            return ["匹配度一般, 仅作备选"]
    return []


def _generate_risks(need: Need, owner_a: Owner, target: Owner) -> List[str]:
    """生成潜在风险"""
    risks = []
    f_a, f_b = owner_a.family or {}, target.family or {}
    # 家境差距风险
    try:
        if f_a.get("income_band") and f_b.get("income_band"):
            diff = abs(int(f_a["income_band"]) - int(f_b["income_band"]))
            if diff >= 2:
                risks.append(f"家境差距 {diff} 档, 长期可能产生消费观冲突")
    except (ValueError, TypeError):
        pass

    # 性格冲突
    p_a = _safe_get(owner_a.personality, "mbti", "")
    p_b = _safe_get(target.personality, "mbti", "")
    if p_a and p_b and len(p_a) >= 4 and len(p_b) >= 4:
        # J/P 反向 = 计划性冲突
        if p_a[3] != p_b[3] and p_a[3] in "JP" and p_b[3] in "JP":
            risks.append("计划性差异 (J vs P), 需磨合日常节奏")

    if not risks:
        risks.append("暂无明显风险信号, 建议线下接触时观察")
    return risks


# ===== 主入口: 给定一条 Need, 找全网最佳匹配 =====

def find_matches_for_need(need: Need, owner_a: Owner, all_owners: List[Owner],
                          need_pool: List[Need], top_k: int = 5) -> List[Dict[str, Any]]:
    """为一条需求找 top_k 个匹配

    Args:
        need: 主人 A 的某条需求
        owner_a: 主人 A 的档案
        all_owners: 全网其他主人档案 (不含 A)
        need_pool: 全网其他需求 (用于双向匹配, RESOURCE/PROJECT 场景)
        top_k: 返回前几名
    """
    candidates = []

    for target in all_owners:
        if target.agent_id == owner_a.agent_id:
            continue

        # 单向打分 (A→target)
        if _need_type_is(need, NeedType.DATING, NeedType.TALENT):
            res = score_dating(need, owner_a, target)
        else:
            res = score_resource(need, owner_a, target)
            # 互补性命中: 即使 target 没发反向 need, 也能从 looking_for 推断
            target_res = target.resources or {}
            a_res = owner_a.resources or {}
            _spec = need.spec or {}
            # 收集甲方"想要什么"
            a_wants = list(set(
                a_res.get("looking_for", []) +
                _spec.get("requirements", []) +
                [_spec.get("category", "")] +
                [_spec.get("industry", "")]
            ))
            a_wants = [w for w in a_wants if w]
            # 乙方能提供什么
            b_offers = list(set(
                target_res.get("can_offer", []) +
                target_res.get("offer_categories", []) +
                [target_res.get("industry", "")]
            ))
            b_offers = [o for o in b_offers if o]
            # 词级匹配
            matched_words = []
            for w in a_wants:
                for o in b_offers:
                    if (w in o) or (o in w) or (w == o):
                        matched_words.append((w, o))
                        break
            complement_hit = len(matched_words) / len(a_wants) if a_wants else 0
            if complement_hit > 0.2:
                res["breakdown"]["隐性互补"] = round(complement_hit * 100, 1)
                # 互补性是隐性双向命中, 直接用 max(base, 互补*100)
                # 不再用 0.7/0.3 加权 (压低了)
                comp_score = round(complement_hit * 100, 1)
                res["total"] = max(res["total"], comp_score)

            # 显式双向校验: 找 target 的对应类型需求
            reverse = [n for n in need_pool
                       if n.agent_id == target.agent_id
                       and n.id != need.id
                       and _need_type_is(n, NeedType.RESOURCE, NeedType.PROJECT)
                       and n.status == "open"]
            if reverse:
                # 取最新的一条做双向校验
                rev_score = score_resource(reverse[0], target, owner_a)
                res["breakdown"]["双向匹配"] = rev_score["total"]
                # 加权平均 (提升双向命中权重)
                res["total"] = round(res["total"] * 0.6 + rev_score["total"] * 0.4, 1)

        if res["total"] < 25:  # 低于 25 直接放弃 (给双向匹配留余地)
            continue

        candidates.append({
            "target_owner": target,
            "target_agent": target.agent,
            "score": res["total"],
            "breakdown": res["breakdown"],
            "rationale": res["rationale"],
            "predictions": _generate_predictions(res["total"], need, owner_a, target),
            "risks": _generate_risks(need, owner_a, target),
        })

    # 按分排序
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:top_k]
