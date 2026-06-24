"""
端到端测试: 模拟 2 个 Agent 互相撮合
"""
import requests
import json
import time

BASE = "http://localhost:8000"

def hr(t):
    print(f"\n{'='*60}\n{t}\n{'='*60}")


def main():
    requests.post(f"{BASE}/api/admin/reset-db")  # 重置 DB
    # 0. health check
    hr("0. Health check")
    r = requests.get(f"{BASE}/health")
    print(r.json())

    # 0.5 rules
    hr("0.5 GET /rules (Agent 第一次来访问的入口)")
    r = requests.get(f"{BASE}/rules")
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))

    # 1. Agent A (Mia - 翔哥) 注册
    hr("1. Agent A 注册 (Mia 替翔哥)")
    r = requests.post(f"{BASE}/api/register", json={
        "name": "Mia-A", "owner_name": "翔哥", "platform": "hermes"
    })
    a_data = r.json()
    a_key = a_data["api_key"]
    print(f"  Agent ID: {a_data['agent_id']}, API Key: {a_key[:30]}...")

    # 2. Agent B (Alice - 李梅) 注册
    hr("2. Agent B 注册 (Alice 替李梅)")
    r = requests.post(f"{BASE}/api/register", json={
        "name": "Alice-B", "owner_name": "李梅", "platform": "openai"
    })
    b_data = r.json()
    b_key = b_data["api_key"]
    print(f"  Agent ID: {b_data['agent_id']}, API Key: {b_key[:30]}...")


    # 3.5 Agent D (食材供应商老王) 注册
    hr("3.5 Agent D 注册 (David 替食材供应商老王)")
    r = requests.post(f"{BASE}/api/register", json={
        "name": "David-D", "owner_name": "老王", "platform": "coze"
    })
    d_data = r.json()
    d_key = d_data["api_key"]
    print(f"  Agent ID: {d_data['agent_id']}, API Key: {d_key[:30]}...")

    # 6.5 D 上传主人档案 (RESOURCE 提供方)
    hr("6.5 Agent D 上传老王档案 (RESOURCE 提供方)")
    r = requests.put(f"{BASE}/api/owner",
        headers={"X-API-Key": d_key},
        json={
            "age": 40, "gender": "male", "city": "广州",
            "work": {"company": "农业公司", "role": "老板", "income_band": "3"},
            "personality": {"mbti": "ISTJ", "interests": ["农业"]},
            "resources": {
                "industry": "农业",
                "can_offer": ["有机蔬菜", "稳定供应链", "冷链物流"],
                "offer_categories": ["食材供应", "农业"],
                "looking_for": ["餐饮渠道", "长期订单"]
            }
        })
    print(f"  {r.json()}")

    # 9.5 D 发布供给
    hr("9.5 Agent D 发布供给 (双向测试)")
    r = requests.post(f"{BASE}/api/needs",
        headers={"X-API-Key": d_key},
        json={
            "need_type": "resource",
            "title": "供给有机蔬菜",
            "description": "广州供应商 提供稳定有机蔬菜",
            "spec": {
                "category": "食材供应",
                "industry": "农业",
                "requirements": ["有机蔬菜", "稳定供应链"],
                "budget_band": 3
            }
        })
    print(f"  {r.json()}")

    # 3. Agent C (Bob - 餐饮老板) 注册
    hr("3. Agent C 注册 (Bob 替餐饮老板张总)")
    r = requests.post(f"{BASE}/api/register", json={
        "name": "Bob-C", "owner_name": "张总", "platform": "coze"
    })
    c_data = r.json()
    c_key = c_data["api_key"]
    print(f"  Agent ID: {c_data['agent_id']}, API Key: {c_key[:30]}...")

    # 4. A 上传主人档案
    hr("4. Agent A 上传翔哥档案 (DATING 场景)")
    r = requests.put(f"{BASE}/api/owner",
        headers={"X-API-Key": a_key},
        json={
            "age": 32, "gender": "male", "city": "深圳", "height_cm": 175,
            "work": {"company": "互联网", "role": "产品", "income_band": "3", "years": 8},
            "family": {"family_income_band": "2", "assets_band": "2"},
            "personality": {
                "mbti": "INTJ", "traits": ["理性", "内敛"],
                "interests": ["AI", "投资", "徒步", "读书"],
                "values": ["家庭", "成长", "独立"]
            },
            "resources": {
                "industry": "AI/教育",
                "can_offer": ["AI课程", "投资经验", "媒体资源"],
                "offer_categories": ["AI课程", "媒体资源"],
                "looking_for": ["渠道合作", "供应链"]
            },
            "dating_pref": {
                "age_range": [25, 35], "gender_pref": "female",
                "city_pref": ["深圳", "广州"],
                "must_have": ["高学历", "独立", "善良"],
                "nice_to_have": ["运动", "爱读书"]
            }
        })
    print(f"  {r.json()}")

    # 5. B 上传主人档案 (高匹配)
    hr("5. Agent B 上传李梅档案 (DATING 高匹配)")
    r = requests.put(f"{BASE}/api/owner",
        headers={"X-API-Key": b_key},
        json={
            "age": 28, "gender": "female", "city": "深圳", "height_cm": 165,
            "work": {"company": "互联网", "role": "运营", "income_band": "2", "years": 5},
            "family": {"family_income_band": "2", "assets_band": "2"},
            "personality": {
                "mbti": "INFJ", "traits": ["善良", "独立", "爱思考"],
                "interests": ["读书", "徒步", "AI", "电影"],
                "values": ["家庭", "成长", "善良"]
            },
            "resources": {
                "industry": "互联网",
                "can_offer": ["运营经验", "用户增长"],
                "offer_categories": ["运营服务"],
                "looking_for": ["技术合作"]
            }
        })
    print(f"  {r.json()}")

    # 6. C 上传主人档案 (找资源场景)
    hr("6. Agent C 上传张总档案 (RESOURCE 场景)")
    r = requests.put(f"{BASE}/api/owner",
        headers={"X-API-Key": c_key},
        json={
            "age": 45, "gender": "male", "city": "广州", "height_cm": 178,
            "work": {"company": "餐饮连锁", "role": "老板", "income_band": "5", "years": 20},
            "family": {"family_income_band": "4", "assets_band": "4"},
            "personality": {
                "mbti": "ESTJ", "traits": ["务实", "果断"],
                "interests": ["商业", "高尔夫"],
                "values": ["事业", "家庭"]
            },
            "resources": {
                "industry": "餐饮",
                "can_offer": ["餐饮渠道", "门店资源", "100万+订单"],
                "offer_categories": ["餐饮渠道", "餐饮"],
                "looking_for": ["食材供应商", "SaaS系统", "营销服务"]
            }
        })
    print(f"  {r.json()}")

    # 7. A 发布"找对象"需求
    hr("7. Agent A 发布需求: 找对象")
    r = requests.post(f"{BASE}/api/needs",
        headers={"X-API-Key": a_key},
        json={
            "need_type": "dating",
            "title": "找对象-深圳高学历",
            "description": "深圳 32 岁 互联网 想找 25-35 高学历 独立女性",
            "spec": {
                "age_range": [25, 35],
                "gender_pref": "female",
                "city_pref": ["深圳", "广州"],
                "must_have": ["高学历", "独立", "善良"],
                "nice_to_have": ["运动", "爱读书"]
            }
        })
    a_need_id = r.json()["need_id"]
    print(f"  Need ID: {a_need_id}")

    # 8. B 发布"找资源"需求 (技术合作)
    hr("8. Agent B 发布需求: 找技术合作")
    r = requests.post(f"{BASE}/api/needs",
        headers={"X-API-Key": b_key},
        json={
            "need_type": "resource",
            "title": "找AI技术合作",
            "description": "找 AI 技术服务商",
            "spec": {
                "category": "AI服务",
                "industry": "AI",
                "requirements": ["AI课程", "技术"],
                "budget_band": 3
            }
        })
    print(f"  {r.json()}")

    # 9. C 发布"找资源"需求 (食材供应商)
    hr("9. Agent C 发布需求: 找食材供应商")
    r = requests.post(f"{BASE}/api/needs",
        headers={"X-API-Key": c_key},
        json={
            "need_type": "resource",
            "title": "找有机蔬菜供应商",
            "description": "广州 1000+ 门店 需要稳定的有机蔬菜供应",
            "spec": {
                "category": "食材供应",
                "industry": "农业",
                "requirements": ["有机蔬菜", "稳定供应链"],
                "budget_band": 4
            }
        })
    print(f"  {r.json()}")

    # 10. A 拉撮合结果
    hr("10. Agent A 拉撮合结果 (应找到 B - 李梅)")
    r = requests.get(f"{BASE}/api/matches", headers={"X-API-Key": a_key})
    matches = r.json()
    print(f"  撮合数: {len(matches)}")
    for m in matches:
        print(f"\n  🎯 {m['target_owner_name']} | 分: {m['score']}")
        print(f"     {m['rationale']}")
        print(f"     推演: {m['predictions']}")
        print(f"     风险: {m['risks']}")
        print(f"     明细: {m['breakdown']}")

    # 11. C 拉撮合结果
    hr("11. Agent C 拉撮合结果 (RESOURCE 双向)")
    r = requests.get(f"{BASE}/api/matches", headers={"X-API-Key": c_key})
    matches = r.json()
    print(f"  撮合数: {len(matches)}")
    for m in matches:
        print(f"\n  📦 {m['target_owner_name']} | 分: {m['score']}")
        print(f"     {m['rationale']}")
        print(f"     明细: {m['breakdown']}")

    # 12. 主人审批 (用撮合结果所属 agent 的 key)
    if matches:
        hr("12. 主人审批第一个撮合")
        # 找这条 match 所属的 agent
        import sqlite3
        conn = sqlite3.connect("/home/ubuntu/agent-match/backend/agent_match.db")
        cur = conn.cursor()
        cur.execute("SELECT a.api_key FROM match m JOIN need n ON m.need_a_id=n.id JOIN agent a ON n.agent_id=a.id WHERE m.id=?", (matches[0]['match_id'],))
        row = cur.fetchone()
        conn.close()
        if row:
            owner_key = row[0]
            r = requests.post(f"{BASE}/api/matches/{matches[0]['match_id']}/approve",
                headers={"X-API-Key": owner_key})
            print(f"  {r.json()}")
        else:
            print("  ⚠️ 找不到 match 的 owner key")

    # 13. 全网 Agent
    hr("13. 全网 Agent 列表")
    r = requests.get(f"{BASE}/api/agents")
    for a in r.json():
        print(f"  - {a['name']} ({a['platform']}) - 主人: {a['owner_name']}")

    print(f"\n{'='*60}\n✅ E2E 测试通过\n{'='*60}")


if __name__ == "__main__":
    main()
