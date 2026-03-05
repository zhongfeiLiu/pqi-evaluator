"""
通过 Notion API 设置 PQI 评估系统数据库
页面 ID: 31aaadc9bc0c8015bbd5ed6ee824f1ac
"""
import requests
import json

NOTION_TOKEN = "os.environ.get("NOTION_TOKEN", "")"
PAGE_ID = "31aaadc9bc0c8015bbd5ed6ee824f1ac"

headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# 步骤1: 尝试读取页面（测试 Integration 是否有权限）
print("步骤1: 测试 Integration 权限...")
resp = requests.get(
    f"https://api.notion.com/v1/pages/{PAGE_ID}",
    headers=headers
)
print(f"状态码: {resp.status_code}")
result = resp.json()

if resp.status_code == 200:
    print("✅ Integration 已有权限访问该页面!")
    print(f"页面标题: {result.get('properties', {}).get('title', {})}")
    
    # 步骤2: 在页面中创建数据库
    print("\n步骤2: 创建 PQI 评估数据库...")
    db_payload = {
        "parent": {"type": "page_id", "page_id": PAGE_ID},
        "icon": {"type": "emoji", "emoji": "🎓"},
        "title": [{"type": "text", "text": {"content": "PQI 导师评估数据库"}}],
        "properties": {
            "导师姓名": {"title": {}},
            "学校/机构": {"rich_text": {}},
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
            "PQI总分": {"number": {"format": "number"}},
            "评级": {
                "select": {
                    "options": [
                        {"name": "⭐⭐⭐⭐⭐ 顶级实验室", "color": "green"},
                        {"name": "⭐⭐⭐⭐ 优秀实验室", "color": "blue"},
                        {"name": "⭐⭐⭐ 稳定实验室", "color": "yellow"},
                        {"name": "⭐⭐ 风险实验室", "color": "orange"},
                        {"name": "⭐ 高危实验室", "color": "red"}
                    ]
                }
            },
            "S-科研产出": {"number": {"format": "number"}},
            "P-导师声誉": {"number": {"format": "number"}},
            "C-课题组文化": {"number": {"format": "number"}},
            "L-学生去向": {"number": {"format": "number"}},
            "F-经费稳定性": {"number": {"format": "number"}},
            "D-风险惩罚": {"number": {"format": "number"}},
            "综合建议": {"rich_text": {}},
            "数据来源": {"rich_text": {}},
            "评估时间": {"date": {}}
        }
    }
    
    db_resp = requests.post(
        "https://api.notion.com/v1/databases",
        headers=headers,
        json=db_payload
    )
    
    print(f"数据库创建状态码: {db_resp.status_code}")
    db_result = db_resp.json()
    
    if db_resp.status_code == 200:
        db_id = db_result["id"]
        db_url = db_result.get("url", "")
        print(f"\n✅ 数据库创建成功!")
        print(f"数据库 ID: {db_id}")
        print(f"数据库 URL: {db_url}")
        
        # 保存 DB ID 到文件
        with open("notion_db_id.txt", "w") as f:
            f.write(db_id)
        print(f"\n数据库 ID 已保存到 notion_db_id.txt")
    else:
        print(f"❌ 数据库创建失败:")
        print(json.dumps(db_result, ensure_ascii=False, indent=2))
        
elif resp.status_code == 404:
    print("❌ Integration 没有权限访问该页面")
    print("需要在 Notion 页面中手动添加 Integration 连接")
    print("\n错误详情:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
else:
    print(f"❌ 其他错误:")
    print(json.dumps(result, ensure_ascii=False, indent=2))
