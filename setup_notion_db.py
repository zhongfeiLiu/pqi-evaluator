"""
Notion 数据库初始化脚本
运行此脚本将在您指定的 Notion 页面中创建 PQI 评估数据库，
并自动配置所有必要的属性字段。

使用方法：
    python setup_notion_db.py

需要提前设置环境变量：
    NOTION_TOKEN=your_token
    NOTION_PARENT_PAGE_ID=your_page_id  （要在哪个页面下创建数据库）
"""

import os
import sys
from notion_client import Client

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
PARENT_PAGE_ID = os.environ.get("NOTION_PARENT_PAGE_ID", "")

if not NOTION_TOKEN or not PARENT_PAGE_ID:
    print("❌ 错误：请设置环境变量 NOTION_TOKEN 和 NOTION_PARENT_PAGE_ID")
    print("\n设置方法（Mac/Linux）：")
    print("  export NOTION_TOKEN=secret_xxx")
    print("  export NOTION_PARENT_PAGE_ID=your_page_id")
    print("\n设置方法（Windows）：")
    print("  set NOTION_TOKEN=secret_xxx")
    print("  set NOTION_PARENT_PAGE_ID=your_page_id")
    sys.exit(1)

notion = Client(auth=NOTION_TOKEN)

print("🚀 正在创建 PQI 3.0 导师评估数据库...")

database = notion.databases.create(
    parent={"type": "page_id", "page_id": PARENT_PAGE_ID},
    title=[{"type": "text", "text": {"content": "🎓 PQI 3.0 导师评估数据库"}}],
    properties={
        # ── 主键：导师姓名 ──────────────────────────────
        "导师姓名": {
            "title": {}
        },
        # ── 输入字段 ────────────────────────────────────
        "学校": {
            "rich_text": {}
        },
        # ── 评估状态 ────────────────────────────────────
        "评估状态": {
            "select": {
                "options": [
                    {"name": "待评估", "color": "gray"},
                    {"name": "评估中", "color": "yellow"},
                    {"name": "已完成", "color": "green"},
                    {"name": "评估失败", "color": "red"}
                ]
            }
        },
        # ── 核心结果 ────────────────────────────────────
        "PQI分数": {
            "number": {"format": "number"}
        },
        "评级": {
            "select": {
                "options": [
                    {"name": "顶级实验室", "color": "green"},
                    {"name": "优秀实验室", "color": "blue"},
                    {"name": "稳定实验室", "color": "yellow"},
                    {"name": "风险实验室", "color": "orange"},
                    {"name": "高危实验室", "color": "red"}
                ]
            }
        },
        "综合建议": {
            "rich_text": {}
        },
        # ── 各维度分数 ──────────────────────────────────
        "S分": {"number": {"format": "number"}},
        "P分": {"number": {"format": "number"}},
        "C分": {"number": {"format": "number"}},
        "L分": {"number": {"format": "number"}},
        "F分": {"number": {"format": "number"}},
        "D惩罚": {"number": {"format": "number"}},
        # ── 时间戳 ──────────────────────────────────────
        "评估时间": {
            "date": {}
        }
    }
)

db_id = database["id"]
db_url = database["url"]

print(f"\n✅ 数据库创建成功！")
print(f"   数据库 ID：{db_id}")
print(f"   数据库 URL：{db_url}")
print(f"\n📋 请将以下信息保存，部署时需要用到：")
print(f"   NOTION_DB_ID={db_id.replace('-', '')}")
print(f"\n⚠️  接下来请手动完成：")
print(f"   1. 打开上方 URL，在数据库中添加一个「评估」按钮（Database Button）")
print(f"   2. 按钮动作选择「Send webhook」，URL 填入您的后端服务地址 + /webhook")
print(f"   3. 在按钮设置中勾选发送「导师姓名」和「学校」属性")
