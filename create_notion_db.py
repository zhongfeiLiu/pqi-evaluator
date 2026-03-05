"""
创建 PQI 评估 Notion 数据库
"""
import requests
import json

NOTION_TOKEN = "os.environ.get("NOTION_TOKEN", "")"

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# 先获取用户信息，找到可以创建数据库的父页面
def get_workspace_pages():
    """搜索工作区中的页面"""
    resp = requests.post(
        "https://api.notion.com/v1/search",
        headers=headers,
        json={"filter": {"value": "page", "property": "object"}, "page_size": 10}
    )
    return resp.json()

def create_pqi_database(parent_page_id: str):
    """创建 PQI 评估数据库"""
    db_payload = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "icon": {"type": "emoji", "emoji": "🎓"},
        "title": [{"type": "text", "text": {"content": "PQI 导师评估数据库"}}],
        "properties": {
            "导师姓名": {"title": {}},
            "学校": {"rich_text": {}},
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
            "PQI分数": {"number": {"format": "number"}},
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
            "S分": {"number": {"format": "number"}},
            "P分": {"number": {"format": "number"}},
            "C分": {"number": {"format": "number"}},
            "L分": {"number": {"format": "number"}},
            "F分": {"number": {"format": "number"}},
            "D惩罚": {"number": {"format": "number"}},
            "综合建议": {"rich_text": {}},
            "评估时间": {"created_time": {}}
        }
    }

    resp = requests.post(
        "https://api.notion.com/v1/databases",
        headers=headers,
        json=db_payload
    )
    return resp.json()

# 第一步：搜索可用页面
print("搜索工作区页面...")
pages_result = get_workspace_pages()

if pages_result.get("results"):
    # 找第一个可用页面作为父页面
    for page in pages_result["results"]:
        page_id = page["id"]
        page_title = ""
        if page.get("properties", {}).get("title", {}).get("title"):
            page_title = page["properties"]["title"]["title"][0]["plain_text"]
        elif page.get("properties", {}).get("Name", {}).get("title"):
            page_title = page["properties"]["Name"]["title"][0]["plain_text"]
        print(f"  找到页面: {page_title} (ID: {page_id})")

    # 使用第一个页面
    parent_id = pages_result["results"][0]["id"]
    print(f"\n使用页面 ID: {parent_id} 作为父页面")

    print("创建 PQI 评估数据库...")
    db_result = create_pqi_database(parent_id)

    if db_result.get("id"):
        db_id = db_result["id"]
        print(f"\n✅ 数据库创建成功!")
        print(f"数据库 ID: {db_id}")
        print(f"数据库 URL: {db_result.get('url', '')}")
    else:
        print(f"❌ 创建失败: {json.dumps(db_result, ensure_ascii=False, indent=2)}")
else:
    print(f"未找到页面: {json.dumps(pages_result, ensure_ascii=False, indent=2)}")
