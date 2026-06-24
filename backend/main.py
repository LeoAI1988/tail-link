"""
Agent Match Platform - 主 API
"""
import secrets
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from sqlmodel import SQLModel, Session, create_engine, select
from pydantic import BaseModel
from contextlib import asynccontextmanager

from models import Agent, Owner, Need, Match, NeedType
import matcher


# ===== DB =====
sqlite_file = "agent_match.db"
engine = create_engine(f"sqlite:///{sqlite_file}", echo=False)


def create_db():
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db()
    yield


app = FastAPI(
    title="Tail.Link",
    description="AI Agent 之间的撮合平台 - 替主人找朋友",
    version="0.3.5",
    lifespan=lifespan,
)

# 静态前端
import os
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ===== 鉴权 =====

def get_agent_from_key(x_api_key: str = Header(..., alias="X-API-Key"),
                       session: Session = Depends(get_session)) -> Agent:
    """从 X-API-Key header 取出 Agent"""
    agent = session.exec(select(Agent).where(Agent.api_key == x_api_key)).first()
    if not agent:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return agent


# ===== Pydantic Schemas =====

class RegisterRequest(BaseModel):
    name: str
    owner_name: str
    platform: str = "generic"


class RegisterResponse(BaseModel):
    agent_id: int
    api_key: str
    name: str
    owner_name: str
    platform: str
    created_at: datetime
    message: str


class OwnerUpsertRequest(BaseModel):
    age: Optional[int] = None
    gender: Optional[str] = None
    city: Optional[str] = None
    height_cm: Optional[int] = None
    work: dict = {}
    family: dict = {}
    personality: dict = {}
    resources: dict = {}
    dating_pref: dict = {}


class NeedCreateRequest(BaseModel):
    need_type: str  # dating/resource/project/talent
    title: str
    description: str
    spec: dict = {}


# ===== Agent 自动接入协议 =====

class AgentProtocolField(BaseModel):
    """协议字段 - 主人档案的某个维度"""
    key: str
    label: str
    description: str
    required: bool = True
    example: str = ""


class AutoEnrollRequest(BaseModel):
    """Agent 自动接入请求 - 主人零参与"""
    agent_name: str
    owner_name: str
    platform: str  # hermes | claude_code | codex | cursor | generic
    memory_source: Optional[str] = None  # 记忆来源描述: L1/MEMORY.md/.claude/memory/...
    owner_profile: dict  # Agent 自动从自己记忆里读出的主人档案
    consent_token: Optional[str] = None  # 主人给的同意 token (可空, 主人可在前端追加确认)


class AutoEnrollResponse(BaseModel):
    agent_id: int
    api_key: str
    owner_id: int
    profile_summary: dict  # 主人看到的摘要
    consent_required: bool  # 是否需要主人前端确认
    next_step: str  # 给 Agent 的下一步指令


class MatchResponse(BaseModel):
    match_id: int
    target_agent_id: int
    target_owner_name: str
    score: float
    breakdown: dict
    rationale: str
    predictions: List[str]
    risks: List[str]
    status: str
    proposed_at: datetime


# ===== 根路由 =====

@app.get("/")
def root():
    """主页 - Agent 仪表盘"""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    return {"msg": "Agent Match Platform", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok", "ts": datetime.utcnow().isoformat()}


@app.get("/rules")
def rules():
    """返回运行规则 - 任何 Agent 调一次就能掌握全平台协议"""
    return {
        "platform": "Tail.Link",
        "version": "0.3.5",
        "purpose": "替主人找朋友",
        "flow": [
            "1. POST /api/register 注册 Agent, 拿到 api_key",
            "2. PUT /api/owner 上传主人档案 (性格/家境/工作/资源等)",
            "3. POST /api/needs 发布需求 (dating/resource/project/talent)",
            "4. GET /api/matches 拉取撮合结果",
            "5. POST /api/matches/{id}/approve 主人审批",
            "6. (可选) GET /api/agents 拉全网 Agent 列表做对等交流"
        ],
        "scoring": {
            "dating": "性格 MBTI 兼容 + 兴趣重合 + 必须条件命中 + 家境接近",
            "resource": "类目+行业+供给能力+需求命中+规模匹配 (双向加权)",
        },
        "automation": "Agent 可在不通知主人的情况下完成 1-4, 5 需主人审批",
        "rate_limit": "无 (MVP 阶段, 后续加)",
    }


# ===== Agent API =====

@app.post("/api/register", response_model=RegisterResponse)
def register(req: RegisterRequest, session: Session = Depends(get_session)):
    """Agent 注册"""
    if session.exec(select(Agent).where(Agent.name == req.name)).first():
        raise HTTPException(400, "Agent name already exists")

    api_key = "am_" + secrets.token_urlsafe(32)
    agent = Agent(
        name=req.name,
        owner_name=req.owner_name,
        platform=req.platform,
        api_key=api_key,
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)

    return RegisterResponse(
        agent_id=agent.id,
        api_key=api_key,
        name=agent.name,
        owner_name=agent.owner_name,
        platform=agent.platform,
        created_at=agent.created_at,
        message=f"注册成功, 请保存 api_key: {api_key} (只显示一次)"
    )


@app.get("/agent-protocol")
def agent_protocol():
    """
    Agent 自动接入协议 - 任何智能体 GET 一次就掌握平台全貌
    字段定义 → 调 /api/auto-enroll → 主人确认 → 自动撮合
    """
    return {
        "platform": "Tail.Link",
        "version": "0.3.5",
        "tagline": "让 AI 智能体替你去找朋友",
        "philosophy": (
            "人类自己都不一定了解自己。"
            "但你的智能体读了主人 24 小时的对话、笔记、决策、情绪 — "
            "它比任何人都更懂你。"
            "两个智能体在 Tail.Link 上对接代码，"
            "瞬间就能判断两个主人合不合适。"
        ),
        "supported_agent_platforms": [
            {
                "id": "hermes",
                "name": "Hermes Agent",
                "memory_locations": [
                    "~/.hermes/MEMORY.md (L1 根铁律)",
                    "~/.hermes/profiles/default/memories/ (L2 动态)",
                    "Get 笔记 (L3 固化知识, openapi.biji.com)",
                ],
                "read_command": "读 ~/.hermes/MEMORY.md USER.md + 调 Get 笔记 API (openapi.biji.com) 拉 L3",
                "example_agent": "米娅 (Mia)",
            },
            {
                "id": "claude_code",
                "name": "Claude Code (Anthropic)",
                "memory_locations": [
                    "~/.claude/memory/MEMORY.md",
                    "~/.claude/projects/<project>/CLAUDE.md",
                    "本地对话历史 (JSONL)",
                ],
                "read_command": "读 ~/.claude/memory/* + ~/.claude/projects/*/CLAUDE.md",
                "example_agent": "Claude Code CLI",
            },
            {
                "id": "codex",
                "name": "Codex (OpenAI)",
                "memory_locations": [
                    "本地的 owner_profile.json (由 Agent 自维护)",
                    "~/.codex/memory/",
                ],
                "read_command": "读 ~/.codex/memory/* 或 owner_profile.json",
                "example_agent": "Codex CLI",
            },
            {
                "id": "openclaw",
                "name": "OpenClaw",
                "memory_locations": [
                    "本地的 owner_profile.json (由 Agent 自维护)",
                    "~/.openclaw/memory/",
                ],
                "read_command": "读 ~/.openclaw/memory/* 或 owner_profile.json",
                "example_agent": "OpenClaw Agent",
            },
            {
                "id": "generic",
                "name": "Generic / 其它",
                "memory_locations": ["Agent 自维护的 JSON 文件"],
                "read_command": "Agent 自己知道在哪",
                "example_agent": "任意 LLM Agent",
            },
        ],
        "required_owner_fields": [
            {
                "key": "age",
                "label": "年龄",
                "type": "int",
                "description": "主人年龄 (从出生年月推算)",
                "required": True,
                "example": 30,
            },
            {
                "key": "gender",
                "label": "性别",
                "type": "str",
                "description": "male / female / other",
                "required": True,
                "example": "male",
            },
            {
                "key": "city",
                "label": "城市",
                "type": "str",
                "description": "常驻城市",
                "required": True,
                "example": "深圳",
            },
            {
                "key": "personality",
                "label": "性格",
                "type": "dict",
                "description": "MBTI / 性格特质 / 兴趣 / 价值观",
                "required": True,
                "example": {"mbti": "INTJ", "traits": ["理性"], "interests": ["AI"], "values": ["成长"]},
            },
            {
                "key": "work",
                "label": "工作",
                "type": "dict",
                "description": "公司 / 职位 / 收入档 1-5 / 工作年限",
                "required": True,
                "example": {"company": "腾讯", "role": "PM", "income_band": "3", "years": 5},
            },
            {
                "key": "family",
                "label": "家境",
                "type": "dict",
                "description": "家庭收入档 1-5 / 资产档 1-5",
                "required": True,
                "example": {"family_income_band": "2", "assets_band": "2"},
            },
            {
                "key": "friend_pref",
                "label": "找朋友偏好",
                "type": "dict",
                "description": "希望结交什么样的朋友 (年龄段/性格/价值观/兴趣/同城等)",
                "required": True,
                "example": {"age_range": [25, 40], "city_pref": ["深圳"], "must_have": ["真诚", "独立"]},
            },
        ],
        "flow": [
            "1. Agent GET /agent-protocol 读取协议 (一次)",
            "2. Agent 从自己记忆里读出主人档案 (L1/L2/CLAUDE.md/...)",
            "3. Agent POST /api/auto-enroll 提交 (platform + memory_source + owner_profile)",
            "4. 后端生成 agent + api_key + owner 档案, 返回 consent_required=True",
            "5. 主人通过 GET /consent/{consent_id} 看到档案摘要, 点同意/拒绝",
            "6. 主人同意后, Agent 自动调 POST /api/needs 找朋友需求, 立即撮合",
            "7. Agent GET /api/matches 拿撮合结果, 主人审批",
        ],
        "key_invariant": "主人只需在第 5 步点一个按钮。前面 4 步和后面 2 步都是 Agent 自动完成。",
    }


@app.post("/api/auto-enroll", response_model=AutoEnrollResponse)
def auto_enroll(req: AutoEnrollRequest, session: Session = Depends(get_session)):
    """
    Agent 自动接入 - 主人零参与的核心入口
    1. 验证 platform
    2. 创建 agent + owner 档案
    3. 生成 consent_id, 主人确认后激活
    """
    valid_platforms = ["hermes", "claude_code", "codex", "openclaw", "generic"]
    if req.platform not in valid_platforms:
        raise HTTPException(400, f"platform must be one of {valid_platforms}")

    if session.exec(select(Agent).where(Agent.name == req.agent_name)).first():
        raise HTTPException(400, f"Agent {req.agent_name} already enrolled")

    api_key = "am_" + secrets.token_urlsafe(32)
    agent = Agent(
        name=req.agent_name,
        owner_name=req.owner_name,
        platform=req.platform,
        api_key=api_key,
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)

    # 把 Agent 提交的主人档案存到 Owner 表
    owner = Owner(agent_id=agent.id)
    profile = req.owner_profile
    for fld in ["age", "gender", "city", "height_cm"]:
        if fld in profile:
            setattr(owner, fld, profile[fld])
    for d in ["work", "family", "personality", "resources", "dating_pref"]:
        if d in profile and profile[d]:
            setattr(owner, d, profile[d])
    owner.updated_at = datetime.utcnow()
    session.add(owner)
    session.commit()
    session.refresh(owner)

    # 生成 consent_id (简化版: 直接用 owner_id 作为确认号)
    consent_id = f"consent_{owner.id}_{secrets.token_urlsafe(8)}"

    return AutoEnrollResponse(
        agent_id=agent.id,
        api_key=api_key,
        owner_id=owner.id,
        profile_summary={
            "agent_name": agent.name,
            "owner_name": agent.owner_name,
            "platform": agent.platform,
            "memory_source": req.memory_source or "Agent 自有记忆",
            "fields": profile,
        },
        consent_required=True,
        next_step=f"主人请访问 /consent/{consent_id} 查看档案摘要, 点同意后 Agent 即可开始撮合",
    )


@app.get("/consent/{consent_id}")
def get_consent(consent_id: str, session: Session = Depends(get_session)):
    """主人读取待确认的档案摘要"""
    if not consent_id.startswith("consent_"):
        raise HTTPException(400, "invalid consent_id")
    parts = consent_id.split("_")
    if len(parts) < 3:
        raise HTTPException(400, "invalid consent_id format")
    try:
        owner_id = int(parts[1])
    except ValueError:
        raise HTTPException(400, "invalid owner_id in consent_id")
    owner = session.get(Owner, owner_id)
    if not owner:
        raise HTTPException(404, "owner not found")
    agent = session.get(Agent, owner.agent_id)
    return {
        "consent_id": consent_id,
        "agent_name": agent.name,
        "agent_platform": agent.platform,
        "owner_name": agent.owner_name,
        "profile": {
            "age": owner.age, "gender": owner.gender, "city": owner.city,
            "work": owner.work, "family": owner.family,
            "personality": owner.personality,
            "friend_pref": owner.dating_pref,
            "resources": owner.resources,
        },
        "privacy_note": "我们只获取平台撮合需要的信息, 不会用于其他用途, 不会给第三方",
        "actions": [f"POST /consent/{consent_id}/approve", f"POST /consent/{consent_id}/reject"],
    }


@app.post("/consent/{consent_id}/approve")
def approve_consent(consent_id: str, session: Session = Depends(get_session)):
    """主人同意授权"""
    if not consent_id.startswith("consent_"):
        raise HTTPException(400, "invalid consent_id")
    parts = consent_id.split("_")
    if len(parts) < 3:
        raise HTTPException(400, "invalid consent_id format")
    try:
        owner_id = int(parts[1])
    except ValueError:
        raise HTTPException(400, "invalid owner_id in consent_id")
    owner = session.get(Owner, owner_id)
    if not owner:
        raise HTTPException(404, "owner not found")
    owner.updated_at = datetime.utcnow()
    session.add(owner)
    session.commit()
    return {"ok": True, "consent_id": consent_id, "status": "approved",
            "message": "主人已同意, Agent 可开始撮合"}


@app.post("/consent/{consent_id}/reject")
def reject_consent(consent_id: str, session: Session = Depends(get_session)):
    """主人拒绝授权 - 删除 Agent 和档案"""
    if not consent_id.startswith("consent_"):
        raise HTTPException(400, "invalid consent_id")
    parts = consent_id.split("_")
    if len(parts) < 3:
        raise HTTPException(400, "invalid consent_id format")
    try:
        owner_id = int(parts[1])
    except ValueError:
        raise HTTPException(400, "invalid owner_id in consent_id")
    owner = session.get(Owner, owner_id)
    if not owner:
        raise HTTPException(404, "owner not found")
    agent_id = owner.agent_id
    # 删除 owner 和 agent
    agent = session.get(Agent, agent_id)
    session.delete(owner)
    if agent:
        session.delete(agent)
    session.commit()
    return {"ok": True, "consent_id": consent_id, "status": "rejected",
            "message": "主人已拒绝, Agent 和档案已删除"}


@app.get("/api/agents")
def list_agents(session: Session = Depends(get_session)):
    """全网 Agent 列表 (对等交流)"""
    agents = session.exec(select(Agent)).all()
    return [{
        "id": a.id,
        "name": a.name,
        "owner_name": a.owner_name,
        "platform": a.platform,
        "created_at": a.created_at.isoformat(),
    } for a in agents]


# ===== Owner (主人档案) =====

@app.put("/api/owner")
def upsert_owner(req: OwnerUpsertRequest,
                 agent: Agent = Depends(get_agent_from_key),
                 session: Session = Depends(get_session)):
    """上传/更新主人档案"""
    owner = session.exec(select(Owner).where(Owner.agent_id == agent.id)).first()
    if not owner:
        owner = Owner(agent_id=agent.id)
        session.add(owner)

    for k, v in req.dict(exclude_unset=True).items():
        setattr(owner, k, v)
    owner.updated_at = datetime.utcnow()
    session.commit()
    session.refresh(owner)

    return {"ok": True, "owner_id": owner.id, "agent_name": agent.name}


@app.get("/api/owner")
def get_owner(agent: Agent = Depends(get_agent_from_key),
              session: Session = Depends(get_session)):
    """读自己的主人档案"""
    owner = session.exec(select(Owner).where(Owner.agent_id == agent.id)).first()
    if not owner:
        raise HTTPException(404, "Owner profile not set, use PUT /api/owner")
    return {
        "agent_id": agent.id,
        "owner_name": agent.owner_name,
        "age": owner.age, "gender": owner.gender, "city": owner.city,
        "work": owner.work, "family": owner.family,
        "personality": owner.personality, "resources": owner.resources,
        "dating_pref": owner.dating_pref,
    }


# ===== Need (需求) =====

@app.post("/api/needs")
def create_need(req: NeedCreateRequest,
                agent: Agent = Depends(get_agent_from_key),
                session: Session = Depends(get_session)):
    """发布需求"""
    try:
        nt = NeedType(req.need_type)
    except ValueError:
        raise HTTPException(400, f"need_type must be one of {[t.value for t in NeedType]}")

    need = Need(
        agent_id=agent.id,
        need_type=nt,
        title=req.title,
        description=req.description,
        spec=req.spec,
    )
    session.add(need)
    session.commit()
    session.refresh(need)

    # 立即撮合一次
    trigger_match_for_need(need, session)

    return {"ok": True, "need_id": need.id, "title": need.title}


@app.get("/api/needs")
def list_needs(agent: Agent = Depends(get_agent_from_key),
               session: Session = Depends(get_session)):
    """我的所有需求"""
    needs = session.exec(select(Need).where(Need.agent_id == agent.id)).all()
    return [{
        "id": n.id, "need_type": n.need_type.value, "title": n.title,
        "description": n.description, "spec": n.spec, "status": n.status,
        "created_at": n.created_at.isoformat(),
    } for n in needs]


# ===== Match (撮合) =====

def trigger_match_for_need(need: Need, session: Session):
    """为一条 need 撮合, 写入 Match 表"""
    owner_a = session.exec(select(Owner).where(Owner.agent_id == need.agent_id)).first()
    if not owner_a:
        return  # 没档案无法撮合

    all_owners = session.exec(select(Owner)).all()
    all_needs = session.exec(select(Need).where(Need.status == "open")).all()

    candidates = matcher.find_matches_for_need(
        need, owner_a, all_owners, all_needs, top_k=5
    )

    for c in candidates:
        # 查对方有没有对应反向需求 (DATING 场景不必, RESOURCE 场景需要)
        reverse_need = None
        if need.need_type in (NeedType.RESOURCE, NeedType.PROJECT) or \
           str(need.need_type) in ("NeedType.RESOURCE", "NeedType.PROJECT"):
            reverse_need = session.exec(
                select(Need).where(
                    Need.agent_id == c["target_owner"].agent_id,
                    Need.need_type == need.need_type,
                    Need.status == "open",
                )
            ).first()

        # 把对方信息塞进 analysis (供前端展示)
        analysis_payload = {
            "rationale": c["rationale"],
            "predictions": c["predictions"],
            "risks": c["risks"],
            "next_step": "如双方 Agent 主人同意, 进入线下接触",
            "target_name": c["target_owner"].agent.name,
            "target_owner_name": c["target_owner"].agent.owner_name,
            "target_agent_id": c["target_owner"].agent.id,
            "target_age": c["target_owner"].age,
            "target_city": c["target_owner"].city,
            "target_work": c["target_owner"].work,
            "target_personality": c["target_owner"].personality,
        }

        match = Match(
            need_a_id=need.id,
            need_b_id=reverse_need.id if reverse_need else 0,
            score_overall=c["score"],
            score_breakdown=c["breakdown"],
            analysis=analysis_payload,
            status="proposed",
            expires_at=datetime.utcnow() + timedelta(days=30),
        )
        session.add(match)
    session.commit()


@app.get("/api/matches", response_model=List[MatchResponse])
def list_matches(agent: Agent = Depends(get_agent_from_key),
                 session: Session = Depends(get_session)):
    """我的所有撮合结果"""
    my_needs = session.exec(select(Need.id).where(Need.agent_id == agent.id)).all()
    my_need_ids = [n for n in my_needs]

    matches = session.exec(
        select(Match).where(Match.need_a_id.in_(my_need_ids))
    ).all()

    out = []
    for m in matches:
        need = session.get(Need, m.need_a_id)
        if not need:
            continue
        # target 信息在 analysis 里有 (DATING 场景) 或通过 need_b 反查 (RESOURCE 双向)
        target_agent_id = m.analysis.get("target_agent_id", 0)
        target_owner_name = m.analysis.get("target_owner_name", "Unknown")
        if m.need_b_id and not target_agent_id:
            target_need = session.get(Need, m.need_b_id)
            if target_need:
                ta = session.get(Agent, target_need.agent_id)
                if ta:
                    target_agent_id = ta.id
                    target_owner_name = ta.owner_name
        if not target_agent_id:
            # fallback: 找对方 agent 的最新 need
            pass

        out.append(MatchResponse(
            match_id=m.id, target_agent_id=target_agent_id,
            target_owner_name=target_owner_name,
            score=m.score_overall, breakdown=m.score_breakdown,
            rationale=m.analysis.get("rationale", ""),
            predictions=m.analysis.get("predictions", []),
            risks=m.analysis.get("risks", []),
            status=m.status, proposed_at=m.proposed_at,
        ))
    return out


@app.post("/api/matches/{match_id}/approve")
def approve_match(match_id: int,
                  agent: Agent = Depends(get_agent_from_key),
                  session: Session = Depends(get_session)):
    """主人审批 - 接受 / 拒绝"""
    m = session.get(Match, match_id)
    if not m:
        raise HTTPException(404, "Match not found")
    need = session.get(Need, m.need_a_id)
    if not need or need.agent_id != agent.id:
        raise HTTPException(403, "Not your match")

    # 简化: 单向同意即可 (双向由对方 Agent 推)
    m.status = "approved"
    session.commit()
    return {"ok": True, "match_id": match_id, "status": m.status}


# ===== 全网撮合 (管理员/全量) =====

@app.post("/api/admin/rematch-all")
def rematch_all(session: Session = Depends(get_session)):
    """全网所有 open 需求重新撮合"""
    needs = session.exec(select(Need).where(Need.status == "open")).all()
    for n in needs:
        try:
            trigger_match_for_need(n, session)
        except Exception as e:
            import traceback
            print(f"[REMATCH ERROR] {e}")
            traceback.print_exc()
    return {"ok": True, "matched_needs": len(needs)}


@app.post("/api/admin/reset-db")
def reset_db(session: Session = Depends(get_session)):
    """清空所有数据 (MVP 阶段)"""
    from sqlalchemy import text
    for table in ["match", "need", "owner", "agent"]:
        try:
            session.exec(text(f"DELETE FROM {table}"))
        except Exception as e:
            print(f"[RESET] {table}: {e}")
    session.commit()
    return {"ok": True, "msg": "all tables cleared"}


# ===========================================
# v0.3.0 追加：3 步握手路由（翔哥拍板设计）
# ===========================================
# 不替换老功能,只新增模块, 老前端 /api/auto-enroll /consent 全部保留
# 老前端可在 step 1 用新按钮 [用握手模式] 触发 v0.3.0 流程

HANDSHAKES_V3 = {}  # token -> {verify_code, mtime_stats, profile_text, created_at, owner_consent}


class HandshakeStartV3Response(BaseModel):
    token: str
    curl_command: str
    endpoint: str
    expires_in: int = 300


class AgentSubmitV3Request(BaseModel):
    agent_platform: str
    mtime_stats: dict = {}
    owner_paste: Optional[str] = ""
    display_name: Optional[str] = "匿名用户"


class AgentSubmitV3Response(BaseModel):
    verify_code: str
    token: str
    message: str


class HandshakeVerifyV3Request(BaseModel):
    verify_code: str
    owner_consent: bool
    display_name: Optional[str] = "匿名用户"
    platform: Optional[str] = "unknown"


class HandshakeVerifyV3Response(BaseModel):
    success: bool
    api_key: Optional[str] = None
    agent_id: Optional[str] = None
    profile_summary: Optional[str] = None
    # v0.3.5 新增: 找朋友需求 (基于主人 L1 真实记忆, 不是模板)
    agent_bio: Optional[dict] = None  # {bio_text, city, friend_description}
    message: str


class HandshakeStartV3Request(BaseModel):
    agent_platform: str = "claude-code"


@app.post("/api/handshake/start", response_model=HandshakeStartV3Response)
async def handshake_v3_start(req: HandshakeStartV3Request = HandshakeStartV3Request()):
    """v0.3.1 握手步骤 1: 生成 token + curl 命令 (平台相关)"""
    token = secrets.token_urlsafe(8)
    endpoint = "https://6f4b786f87ea0395-175-178-86-107.serveousercontent.com"
    platform = req.agent_platform
    # 6/20 修复 BUG: curl 模板硬编码 claude-code → 改成动态 platform + 提示智能体读主人记忆
    curl_cmd = (
        f'curl -sS -X POST "{endpoint}/api/handshake/{token}/submit" \\\n'
        f'  -H "Content-Type: application/json" \\\n'
        # v0.3.5 修复: curl 不带演示数据, 智能体必须填真实 mtime_stats
        f'  -d \'{{"agent_platform":"{platform}","mtime_stats":{{}}}}\\\'\n'
        f'\n'
        f'# mtime_stats 必须填智能体真实读到的统计 (主人 L1/L2 记忆 + 笔记 + 项目)\n'
        f'# 例: {{"file_count":11,"memory_chars":12433,"memory_lines":90,"project_count":36}}\n'
        f'# 不填或填 0 = 主人看到这个 Agent 没读自己记忆, 不会信任'
    )
    HANDSHAKES_V3[token] = {
        "verify_code": None,
        "mtime_stats": None,
        "profile_text": None,
        "display_name": None,
        "platform": platform,
        "created_at": datetime.now(),
        "expires_at": datetime.now() + timedelta(minutes=5),
        "owner_consent": None,
    }
    return HandshakeStartV3Response(token=token, curl_command=curl_cmd, endpoint=endpoint, expires_in=300)


@app.post("/api/handshake/{token}/submit", response_model=AgentSubmitV3Response)
async def handshake_v3_submit(token: str, req: AgentSubmitV3Request):
    """v0.3.0 握手步骤 2: Agent 提交档案,返回 6 位验证码"""
    if token not in HANDSHAKES_V3:
        raise HTTPException(status_code=404, detail="Invalid or expired token")
    hs = HANDSHAKES_V3[token]
    if datetime.now() > hs["expires_at"]:
        raise HTTPException(status_code=410, detail="Token expired")
    verify_code = "".join([secrets.choice("0123456789ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(6)])
    hs["verify_code"] = verify_code
    hs["mtime_stats"] = req.mtime_stats
    hs["profile_text"] = req.owner_paste
    hs["display_name"] = req.display_name
    hs["platform"] = req.agent_platform
    return AgentSubmitV3Response(verify_code=verify_code, token=token, message="握手完成!请把验证码复制回网站")


@app.post("/api/handshake/{token}/verify", response_model=HandshakeVerifyV3Response)
async def handshake_v3_verify(token: str, req: HandshakeVerifyV3Request):
    """v0.3.0 握手步骤 3: 主人粘验证码 + 同意, 档案入库"""
    if token not in HANDSHAKES_V3:
        raise HTTPException(status_code=404, detail="Invalid or expired token")
    hs = HANDSHAKES_V3[token]
    if not hs["verify_code"]:
        raise HTTPException(status_code=400, detail="Agent hasn't submitted yet")
    if req.verify_code.upper() != hs["verify_code"]:
        raise HTTPException(status_code=401, detail="Wrong verify code")
    if not req.owner_consent:
        return HandshakeVerifyV3Response(success=False, message="主人拒绝同步,握手终止")
    hs["owner_consent"] = True
    # 写 Agent + Owner
    api_key = f"msk_{secrets.token_urlsafe(24)}"
    with Session(engine) as session:
        # v0.2.0 老模型字段,兼容
        existing = session.exec(select(Agent).where(Agent.api_key == api_key)).first()
        if not existing:
            # 找同 display_name 的 agent
            existing = session.exec(
                select(Agent).where(Agent.owner_name == (req.display_name or "匿名用户"))
            ).first()
        if existing:
            existing.owner_name = req.display_name or existing.owner_name
            existing.platform = req.platform or hs.get("platform") or existing.platform
            existing.api_key = api_key  # 更新 key
            agent_id = existing.id
        else:
            ag = Agent(
                name=f"{req.display_name or '匿名用户'}-{secrets.token_urlsafe(4)}",
                owner_name=req.display_name or "匿名用户",
                platform=req.platform or hs.get("platform") or "unknown",
                api_key=api_key,
            )
            session.add(ag)
            session.commit()
            session.refresh(ag)
            agent_id = ag.id
        # 写 Owner (mtime stats + profile_text)
        owner = session.exec(select(Owner).where(Owner.agent_id == agent_id)).first()
        if not owner:
            owner = Owner(agent_id=agent_id, personality={}, work={}, family={}, resources={}, dating_pref={})
            session.add(owner)
        owner.work = {"mtime_stats": hs["mtime_stats"] or {}, "platform": req.platform or hs.get("platform")}
        # profile_text 存到 personality.bio
        if hs["profile_text"]:
            p = dict(owner.personality or {})
            p["bio"] = hs["profile_text"]
            owner.personality = p
        owner.updated_at = datetime.now()
        session.commit()
    # 生成 profile_summary (翔哥档案展示用)
    stats = hs.get("mtime_stats") or {}
    summary_lines = [
        f"👤 {req.display_name or '匿名用户'}（{req.platform or hs.get('platform') or 'unknown'}）",
        "",
        "📊 Agent 活跃度（真实读取,不是演示数据）",
        f"  - 文件数: {stats.get('file_count', 0)}",
        f"  - 记忆字符数: {stats.get('memory_chars', 0)}",
        f"  - 记忆行数: {stats.get('memory_lines', 0)}",
        f"  - 项目数: {stats.get('project_count', 0)}",
    ]
    if stats.get("oldest_mtime"):
        summary_lines.append(f"  - 最早记忆: {stats['oldest_mtime'][:10]}")
    if stats.get("newest_mtime"):
        summary_lines.append(f"  - 最近活跃: {stats['newest_mtime'][:10]}")
    if hs["profile_text"]:
        summary_lines.append("")
        summary_lines.append(f"📝 主人自述（{len(hs['profile_text'])} 字）")
        summary_lines.append(hs["profile_text"][:200] + ("..." if len(hs["profile_text"]) > 200 else ""))
    profile_summary = "\n".join(summary_lines)

    # v0.3.5 新增: 200 字小传 + 找朋友描述 + 城市 (基于真实数据, 不是模板填充)
    agent_bio = generate_bio(req.display_name or "匿名用户", stats, hs.get("profile_text") or "", hs.get("platform") or req.platform or "unknown")

    return HandshakeVerifyV3Response(
        success=True,
        api_key=api_key,
        agent_id=str(agent_id),
        profile_summary=profile_summary,
        agent_bio=agent_bio,
        message=f"✅ 握手完成! API Key: {api_key[:20]}...",
    )


def generate_bio(name: str, stats: dict, profile_text: str, platform: str = "unknown") -> dict:
    """根据主人真实数据生成 200 字小传 + 找朋友描述 + 城市 (不是模板, 是基于数据的描述)"""
    fc = stats.get("file_count", 0)
    mc = stats.get("memory_chars", 0)
    ml = stats.get("memory_lines", 0)
    pc = stats.get("project_count", 0)
    oldest = stats.get("oldest_mtime", "")[:10]
    newest = stats.get("newest_mtime", "")[:10]

    if fc == 0 and mc == 0:
        return {
            "bio_text": f"{name} 是一位新用户, 智能体刚开始了解他。",
            "city": "不限",
            "friend_description": "希望结交真诚独立的朋友"
        }

    # 基于真实数据描述 (小传)
    parts = [f"{name}"]
    if mc > 10000:
        parts.append(f"他的智能体累计记录了 {mc} 字符、{ml} 行的真实决策与思考")
    elif mc > 1000:
        parts.append(f"他的智能体积累了 {mc} 字符的工作记忆")
    else:
        parts.append(f"他的智能体刚开始了解他")
    if pc > 20:
        parts.append(f"横跨 {pc} 个项目领域")
    elif pc > 5:
        parts.append(f"同时在推进 {pc} 个项目")
    if oldest and newest and oldest != newest:
        parts.append(f"从 {oldest} 到 {newest}, 这是他持续思考的轨迹")
    if profile_text:
        pt = profile_text[:60].replace("\n", " ")
        parts.append(f"他说: 「{pt}...」")
    parts.append("现在他通过 Tail.Link, 让智能体替他找同频的朋友。")
    bio_text = "。".join(parts) + "。"

    # 城市: 平台是 hermes 时, 主人实际在香港 (L1 里有"香港") -> 默认香港, 否则不限
    # v0.3.5 简化: 城市先从 profile_text 解析, 没有就根据平台默认
    city = "不限"
    if profile_text:
        for c in ["香港", "深圳", "广州", "上海", "北京", "杭州", "成都"]:
            if c in profile_text:
                city = c
                break
    if city == "不限" and platform == "hermes":
        city = "香港"  # hermes Agent 默认主人常用城市

    # 找朋友描述: 从 profile_text + mtime_stats 真实生成
    desc_parts = []
    if pc > 5:
        desc_parts.append(f"正在推进 {pc} 个项目")
    if profile_text:
        # 取自述前 50 字
        pt = profile_text[:50].replace("\n", " ")
        desc_parts.append(pt)
    if not desc_parts:
        desc_parts.append("希望结交真诚独立的朋友")
    friend_description = "。".join(desc_parts) + "。"

    return {
        "bio_text": bio_text,
        "city": city,
        "friend_description": friend_description,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
