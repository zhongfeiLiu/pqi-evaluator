"""
本地测试脚本 - 不需要 Notion，直接测试 DeepSeek 评估功能
使用方法：
    export DEEPSEEK_API_KEY=sk-xxx
    python test_local.py
"""

import os
import json
import sys

# 临时设置环境变量（测试用）
os.environ.setdefault("NOTION_TOKEN", "test")
os.environ.setdefault("NOTION_DB_ID", "test")

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_API_KEY:
    print("❌ 请设置 DEEPSEEK_API_KEY 环境变量")
    sys.exit(1)

from app import evaluate_mentor_with_deepseek, format_notion_report

# 测试导师（可修改）
TEST_MENTOR = "张三"
TEST_INSTITUTION = "清华大学"

print(f"🔍 正在评估：{TEST_MENTOR} @ {TEST_INSTITUTION}")
print("⏳ 请稍候，DeepSeek 正在搜索并分析数据...\n")

try:
    result = evaluate_mentor_with_deepseek(TEST_MENTOR, TEST_INSTITUTION)

    print("=" * 60)
    print("📊 评估结果（JSON）")
    print("=" * 60)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    print("\n" + "=" * 60)
    print("📝 Notion 报告预览")
    print("=" * 60)
    print(format_notion_report(result))

except Exception as e:
    print(f"❌ 评估失败：{e}")
    import traceback
    traceback.print_exc()
