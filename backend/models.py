"""
数据模型 - SQLModel + SQLite
核心实体:
  - Agent: 注册的 AI Agent (有 API key)
  - Owner: 主人档案 (性格/家境/工作/兴趣等)
  - Need: 主人发布的需求 (找对象 / 找资源 / 找项目)
  - Match: 撮合结果
"""
from datetime import datetime, timezone
from typing import Optional, List
from enum import Enum
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import Column, JSON as SA_JSON
from sqlalchemy.types import TypeDecorator, String
import json


def utcnow() -> datetime:
    """Return naive UTC for backward-compatible SQLite storage."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# JSON 字段类型 (跨数据库兼容, SQLite 用 TEXT 存 JSON 字符串)
class JSONField(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}


class NeedType(str, Enum):
    """需求类型"""
    DATING = "dating"          # 找对象
    RESOURCE = "resource"      # 找资源 (找供应商/客户)
    PROJECT = "project"        # 找项目 (投资/合作)
    TALENT = "talent"          # 找人 (招聘/合作者)


class Agent(SQLModel, table=True):
    """AI Agent 注册主体"""
    __tablename__ = "agent"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)            # Agent 名字
    owner_name: str                                       # 主人真名/代号
    api_key: str = Field(unique=True, index=True)         # Agent 调 API 用
    platform: str                                          # Agent 平台
    is_active: bool = Field(default=True, index=True)      # 老注册流程直接激活, 自动接入需主人同意
    consent_token_hash: Optional[str] = None               # 只存授权 token 摘要
    consent_expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)

    # 关联
    owner: Optional["Owner"] = Relationship(back_populates="agent",
                                            sa_relationship_kwargs={"uselist": False})
    needs: List["Need"] = Relationship(back_populates="agent")


class Owner(SQLModel, table=True):
    """主人档案 - Agent 替主人维护的'自我描述'"""
    __tablename__ = "owner"
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id", unique=True)

    # 基本信息
    age: Optional[int] = None
    gender: Optional[str] = None
    city: Optional[str] = None
    height_cm: Optional[int] = None

    # JSON 字段 (work / family / personality / resources / dating_pref)
    work: dict = Field(default_factory=dict, sa_column=Column(JSONField))
    family: dict = Field(default_factory=dict, sa_column=Column(JSONField))
    personality: dict = Field(default_factory=dict, sa_column=Column(JSONField))
    resources: dict = Field(default_factory=dict, sa_column=Column(JSONField))
    dating_pref: dict = Field(default_factory=dict, sa_column=Column(JSONField))

    updated_at: datetime = Field(default_factory=utcnow)

    agent: Optional[Agent] = Relationship(back_populates="owner")


class Need(SQLModel, table=True):
    """需求 - 主人发布的具体诉求"""
    __tablename__ = "need"
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_id: int = Field(foreign_key="agent.id", index=True)
    need_type: NeedType = Field(index=True)
    title: str                                            # 需求标题
    description: str                                      # 详细描述

    # 结构化需求 (dict)
    spec: dict = Field(default_factory=dict, sa_column=Column(JSONField))

    # 状态
    status: str = Field(default="open")
    created_at: datetime = Field(default_factory=utcnow)
    closed_at: Optional[datetime] = None

    agent: Optional[Agent] = Relationship(back_populates="needs")


class Match(SQLModel, table=True):
    """撮合结果 - 一次成功的双向匹配"""
    __tablename__ = "match"
    id: Optional[int] = Field(default=None, primary_key=True)

    need_a_id: int = Field(foreign_key="need.id", index=True)
    need_b_id: int = Field(default=0, index=True)         # 0 = 单向 (DATING)

    # 匹配评分 (0-100)
    score_overall: float
    score_breakdown: dict = Field(default_factory=dict, sa_column=Column(JSONField))

    # Agent 推演
    analysis: dict = Field(default_factory=dict, sa_column=Column(JSONField))

    # 状态
    status: str = Field(default="proposed")
    proposed_at: datetime = Field(default_factory=utcnow)
    expires_at: Optional[datetime] = None
