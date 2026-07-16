# Tail.Link 部署指南

> AI 智能体撮合平台 · v0.3.6
> 技术栈：FastAPI + SQLModel + SQLite + 原生 HTML/CSS

---

## 一、项目结构

```
tail-link/
├── backend/              # FastAPI 后端
│   ├── main.py           # 主 API、鉴权与授权流程
│   ├── models.py         # SQLModel 数据模型
│   ├── matcher.py        # 双引擎匹配算法
│   ├── requirements.txt  # Python 依赖
│   └── agent_match.db    # SQLite (运行时自动生成)
├── frontend/
│   └── index.html        # 单页前端 (~52KB)
├── docs/
│   └── PRD.md            # 产品需求文档
├── tests/
│   └── test_e2e.py       # 端到端测试
├── deploy/               # 部署配置
│   ├── deploy.sh         # 一键部署脚本
│   ├── tail-link.service # systemd 服务
│   └── nginx-tail-link.conf  # Nginx 配置
├── README.md
└── .gitignore
```

## 二、部署架构

```
用户浏览器 ──https──▶ Nginx (443) ──反代──▶ uvicorn (127.0.0.1:8000)
                         │                        │
                    Let's Encrypt            FastAPI App
                     证书自动续期            (serve index.html + API)
```

- **Nginx**：处理 HTTPS、反向代理
- **uvicorn**：跑 FastAPI，1 worker（SQLite + 内存握手状态要求）
- **systemd**：守护进程，崩溃自动重启
- **SQLite**：文件数据库，无需额外服务

## 三、本地运行

```bash
cd backend
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

访问 http://localhost:8000

## 四、服务器部署（腾讯云轻量 + 域名）

### 前置条件（需用户准备）
1. **腾讯云轻量服务器**：Ubuntu 22.04，2 核 2G 起步
2. **服务器公网 IP + SSH 登录方式**
3. **已备案域名**（中国内地服务器要求）或使用中国香港/海外节点免备案
4. **域名 DNS 解析**：A 记录指向服务器公网 IP

### 一键部署
```bash
# SSH 登录服务器后
git clone https://github.com/LeoAI1988/tail-link.git /opt/tail-link
cd /opt/tail-link
sudo DOMAIN=www.taillink.cloud REPO_URL=https://github.com/LeoAI1988/tail-link.git bash deploy/deploy.sh
```

脚本会自动：保留并迁移现有数据库 → 安装依赖 → 生成管理令牌 → 配置 systemd → 配置 Nginx → 申请 HTTPS 证书 → 线上健康检查。

生产数据位于 `/var/lib/tail-link/agent_match.db`，服务密钥位于 `/etc/tail-link.env`（仅 root 可读）。管理接口必须携带 `X-Admin-Token`，未配置令牌时管理接口默认关闭。

### 域名解析配置
在域名注册商后台添加：
| 类型 | 主机记录 | 记录值 |
|------|---------|--------|
| A    | @       | 服务器公网IP |
| A    | www     | 服务器公网IP |

## 五、常用运维命令

```bash
systemctl status tail-link      # 查看服务状态
systemctl restart tail-link     # 重启服务
journalctl -u tail-link -f      # 实时日志
nginx -t && systemctl reload nginx   # 重载 Nginx
certbot renew --dry-run         # 测试证书续期
```
