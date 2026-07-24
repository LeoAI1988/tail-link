from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "index.html"


def test_homepage_is_a_static_company_filing_page():
    html = FRONTEND.read_text(encoding="utf-8")

    for text in (
        "深圳念新科技有限公司",
        "法人",
        "高翔",
        "办公技能的培训",
        "深圳市福田区碧华庭居清园1栋2B",
        "13751196386",
        "348942587@qq.com",
    ):
        assert text in html

    for marker in ("<script", "onclick=", "<form", "/api/", "智能体替你找朋友"):
        assert marker not in html

    assert "粤ICP备2026089185号" in html
    assert 'href="https://beian.miit.gov.cn/"' in html
