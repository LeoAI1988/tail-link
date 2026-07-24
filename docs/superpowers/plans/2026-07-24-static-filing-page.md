# Static Filing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the public Tail.Link homepage with a non-interactive static company-information page suitable for the filing revision.

**Architecture:** Keep the existing single `frontend/index.html` entry point served by FastAPI, but replace its interactive matching UI and JavaScript with semantic HTML and embedded CSS only. Preserve the dark Tail.Link visual identity and logo while using a compact central information block for the legal company details.

**Tech Stack:** Static HTML5 and CSS3; Python `pytest` source-inspection test.

## Global Constraints

- The homepage must contain no JavaScript, no event handlers, no forms, and no API references.
- Retain a footer with 粤ICP备2026089185号 linking to `https://beian.miit.gov.cn/`; this is the sole external link.
- Remove the former intelligent-agent matching copy, entry card, old page tag, and old ICP footer copy.
- Display exactly: 深圳念新科技有限公司; 法人：高翔; 办公技能培训; 深圳市福田区碧华庭居清园1栋2B; 13751196386; 348942587@qq.com.
- Retain only static branding plus the company-information content in the visible page.

---

### Task 1: Lock the filing-page requirements with a source-level regression test

**Files:**
- Create: `tests/test_static_filing_page.py`
- Test: `tests/test_static_filing_page.py`

**Interfaces:**
- Consumes: `frontend/index.html` read as UTF-8.
- Produces: a test that verifies the required company content and rejects former interactive matching-page markers.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "index.html"


def test_homepage_is_a_static_company_filing_page():
    html = FRONTEND.read_text(encoding="utf-8")

    for text in (
        "深圳念新科技有限公司",
        "法人：高翔",
        "办公技能培训",
        "深圳市福田区碧华庭居清园1栋2B",
        "13751196386",
        "348942587@qq.com",
    ):
        assert text in html

    for marker in ("<script", "onclick=", "<form", "/api/", "智能体替你找朋友"):
        assert marker not in html
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `C:\\QClawWork\\tail-link-static-filing-20260724\\.venv` is not required; use the project environment's Python with `-m pytest tests/test_static_filing_page.py -v`.

Expected: FAIL because the existing page contains the old interactive matching UI and lacks the specified company details.

- [ ] **Step 3: Implement the minimal static page**

Replace `frontend/index.html` with UTF-8 HTML containing the retained Tail.Link visual mark, a company-information `<main>` block, the required ICP footer link, and CSS only. Do not include scripts, buttons, other links, forms, API paths, or user interaction.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_static_filing_page.py -v`.

Expected: PASS with one collected test.

- [ ] **Step 5: Commit**

```bash
git add frontend/index.html tests/test_static_filing_page.py docs/superpowers/plans/2026-07-24-static-filing-page.md
git commit -m "Replace homepage with static filing page"
```

### Task 2: Validate the production artifact and publish it

**Files:**
- Modify: `frontend/index.html`
- Test: `tests/test_static_filing_page.py`

**Interfaces:**
- Consumes: the committed static homepage.
- Produces: a branch published to GitHub and a deployment verified at the configured Tail.Link domain.

- [ ] **Step 1: Run the full test suite**

Run: `python -m pytest -q`.

Expected: zero failing tests.

- [ ] **Step 2: Inspect the rendered static document**

Run a local HTTP server for `frontend/`, load `index.html`, and confirm it has the Tail.Link mark plus only the central legal-information block, with no matching controls or old footer.

- [ ] **Step 3: Publish the committed branch**

Run: `git push -u origin codex/static-filing-page`.

Expected: remote branch is created without modifying `main` until the reviewed change is merged.

- [ ] **Step 4: Deploy the reviewed branch through the existing server process**

After the branch is merged to `main`, update the server checkout to `origin/main`, restart `tail-link`, and request the configured HTTPS domain.

- [ ] **Step 5: Verify the live page**

Request the configured domain and confirm HTTP success plus all six required details; confirm no `script`, `/api/`, or former matching copy appears in the response.
