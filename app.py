"""
PQI 3.0 导师评估后端服务 v3.0
- 使用 Gemini 2.5 Flash + Google Search 实时搜索公开资料
- 通过 Notion API 将结果写回数据库
"""

import os
import json
import logging
import threading
import datetime
from flask import Flask, request, jsonify, render_template
from notion_client import Client

# ── 日志配置 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── 环境变量 ──────────────────────────────────────────────
NOTION_TOKEN     = os.environ.get("NOTION_TOKEN", "")
NOTION_DB_ID     = os.environ.get("NOTION_DB_ID", "")
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "")
WEBHOOK_SECRET   = os.environ.get("WEBHOOK_SECRET", "")

# ── 客户端延迟初始化 ──────────────────────────────────────
_notion_client = None

def get_notion_client():
    global _notion_client
    if _notion_client is None:
        _notion_client = Client(auth=os.environ.get("NOTION_TOKEN", ""))
    return _notion_client

# ═══════════════════════════════════════════════════════════
#  PQI 3.0 评估核心（Gemini 2.5 Flash + Google Search）
# ═══════════════════════════════════════════════════════════

PQI_PROMPT_TEMPLATE = """你是一位专业的学术导师评估专家，使用 PQI 3.0（PI Quality Index）模型对研究生导师进行量化评估。

## 你的任务
请对以下导师进行全面的 PQI 3.0 评估：
- **导师姓名**：{mentor_name}
- **所在学校/机构**：{institution}

## 第一步：信息收集（使用 Google Search 搜索以下内容）
1. 该导师的 Google Scholar 主页 → 获取 h-index、总引用数、近5年论文数
2. 学校/院系官网个人主页 → 获取建组时间、研究方向
3. 实验室官网 → 获取学生列表、毕业生去向（Alumni）
4. 国家自然科学基金委官网 → 获取在研项目和经费信息
5. 学术数据库（Web of Science、PubMed 等）→ 验证论文质量

## 第二步：按 PQI 3.0 公式评分

### S：学生论文质量（权重 35%）
S = 0.7 × Mean(Top5学生论文评分) + 0.3 × Median(Top10学生论文评分)
期刊评分：Nature/Science/Cell系列 Top 1% → 1.0 | CNS子刊/顶级专业期刊 Top 5% → 0.8 | 主流SCI Top 20% → 0.5 | 其余 → 0.2
若学生数据不足，用导师自身论文质量估算，并注明。

### P：导师科研能力（权重 20%）
P = 0.7 × P_paper + 0.3 × P_citation
P_paper = min(近5年高水平通讯/第一作者论文数 / 10, 1)
P_citation = min(h-index / 50, 1)

### C：学生去向指数（权重 20%）
C = 去向评分总和 / 入组学生人数
去向评分：顶级高校教职→1.0 | 海外Top20博后→0.8 | 国内985教职→0.7 | 国家级科研机构→0.6 | 一线大厂研究岗→0.5 | 普通企业→0.2 | 未知→0.3（估算）

### L：实验室稳定度（权重 15%）
L = min(建组年数 / 10, 1)
建组年数 = 当前年份 - 导师独立建组年份

### F：经费指数（权重 10%）
F = min(5年总经费 / 500万人民币, 1)
参考：国家重大项目(>500万)→1.0 | 重点基金(>200万)→0.8 | 面上项目→0.6 | 青年基金→0.4 | 无稳定经费→0.2

### D：淘汰率惩罚
D = (退学 + 转组 + 超7年延毕人数) / 入组总人数
PQI = 0.35×S + 0.20×P + 0.20×C + 0.15×L + 0.10×F
PQI_final = PQI - 0.5×D（最小值为0）

## 评级标准
≥0.85 → 顶级实验室 | 0.70-0.85 → 优秀实验室 | 0.55-0.70 → 稳定实验室 | 0.40-0.55 → 风险实验室 | <0.40 → 高危实验室

## 第三步：输出结果（严格按以下 JSON 格式，不要输出其他内容）
{{
  "mentor_name": "{mentor_name}",
  "institution": "{institution}",
  "scores": {{
    "S": 0.0,
    "P": 0.0,
    "C": 0.0,
    "L": 0.0,
    "F": 0.0,
    "D": 0.0,
    "PQI": 0.0,
    "PQI_final": 0.0
  }},
  "rating": "评级",
  "data_sources": {{
    "S": "具体数据来源，如：Google Scholar显示学生在Nature发表X篇",
    "P": "具体数据来源，如：h-index=XX，近5年通讯作者论文X篇",
    "C": "具体数据来源，如：实验室官网Alumni页面，X名毕业生中Y名去往...",
    "L": "具体数据来源，如：官网显示建组于XXXX年",
    "F": "具体数据来源，如：基金委数据库显示在研项目X项",
    "D": "具体数据来源，如：公开信息未发现异常退学记录"
  }},
  "confidence": {{
    "S": "高/中/低",
    "P": "高/中/低",
    "C": "高/中/低",
    "L": "高/中/低",
    "F": "高/中/低",
    "D": "高/中/低"
  }},
  "key_findings": [
    "关键发现1（基于真实搜索数据）",
    "关键发现2",
    "关键发现3"
  ],
  "recommendation": "综合建议（200字以内，具体、有针对性）",
  "warnings": ["风险提示1（如有，否则空数组）"],
  "disclaimer": "数据说明：本评估基于公开网络资料，部分数据为估算值，仅供参考，建议结合面试和学长学姐反馈综合判断。"
}}"""


def evaluate_mentor_with_gemini(mentor_name: str, institution: str) -> dict:
    """使用 Gemini 2.5 Flash + Google Search 对导师进行 PQI 3.0 评估"""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY 未配置")

    client = genai.Client(api_key=api_key)

    prompt = PQI_PROMPT_TEMPLATE.format(
        mentor_name=mentor_name,
        institution=institution
    )

    logger.info(f"开始 Gemini 评估: {mentor_name} @ {institution}")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.1,
        )
    )

    raw_content = response.text
    logger.info(f"Gemini 返回内容长度: {len(raw_content)}")

    # 提取 JSON（Gemini 有时会在 JSON 前后加说明文字）
    import re
    json_match = re.search(r'\{[\s\S]*\}', raw_content)
    if not json_match:
        raise ValueError(f"Gemini 返回内容中未找到 JSON: {raw_content[:200]}")

    json_str = json_match.group(0)
    result = json.loads(json_str)

    # 确保 PQI 计算正确（防止 AI 算错）
    scores = result.get("scores", {})
    S = float(scores.get("S", 0))
    P = float(scores.get("P", 0))
    C = float(scores.get("C", 0))
    L = float(scores.get("L", 0))
    F = float(scores.get("F", 0))
    D = float(scores.get("D", 0))

    # 强制重新计算（确保公式正确）
    PQI = 0.35 * S + 0.20 * P + 0.20 * C + 0.15 * L + 0.10 * F
    PQI_final = max(0.0, PQI - 0.5 * D)

    result["scores"]["PQI"] = round(PQI, 3)
    result["scores"]["PQI_final"] = round(PQI_final, 3)

    # 强制重新计算评级
    if PQI_final >= 0.85:
        result["rating"] = "顶级实验室"
    elif PQI_final >= 0.70:
        result["rating"] = "优秀实验室"
    elif PQI_final >= 0.55:
        result["rating"] = "稳定实验室"
    elif PQI_final >= 0.40:
        result["rating"] = "风险实验室"
    else:
        result["rating"] = "高危实验室"

    logger.info(f"评估完成: PQI_final={PQI_final:.3f}, 评级={result['rating']}")
    return result


def format_notion_report(eval_result: dict) -> str:
    """将评估结果格式化为 Notion 友好的文本报告"""
    scores = eval_result.get("scores", {})
    confidence = eval_result.get("confidence", {})
    data_sources = eval_result.get("data_sources", {})
    key_findings = eval_result.get("key_findings", [])
    warnings = eval_result.get("warnings", [])

    pqi_final = scores.get("PQI_final", 0)
    rating = eval_result.get("rating", "未知")

    report_lines = [
        f"PQI 3.0 评估报告",
        f"导师：{eval_result.get('mentor_name', '')}  |  机构：{eval_result.get('institution', '')}",
        f"最终评分：{pqi_final:.3f}  →  {rating}",
        "",
        "各维度得分",
        f"S 学生论文质量 (35%): {scores.get('S', 0):.2f} [{confidence.get('S', '-')}] - {data_sources.get('S', '-')}",
        f"P 导师科研能力 (20%): {scores.get('P', 0):.2f} [{confidence.get('P', '-')}] - {data_sources.get('P', '-')}",
        f"C 学生去向 (20%): {scores.get('C', 0):.2f} [{confidence.get('C', '-')}] - {data_sources.get('C', '-')}",
        f"L 实验室稳定度 (15%): {scores.get('L', 0):.2f} [{confidence.get('L', '-')}] - {data_sources.get('L', '-')}",
        f"F 经费指数 (10%): {scores.get('F', 0):.2f} [{confidence.get('F', '-')}] - {data_sources.get('F', '-')}",
        f"D 淘汰率惩罚: {scores.get('D', 0):.2f} [{confidence.get('D', '-')}] - {data_sources.get('D', '-')}",
        f"PQI (原始): {scores.get('PQI', 0):.3f}",
        f"PQI_final: {pqi_final:.3f}",
        "",
    ]

    if key_findings:
        report_lines.append("关键发现")
        for finding in key_findings:
            report_lines.append(f"• {finding}")
        report_lines.append("")

    if warnings:
        report_lines.append("风险提示")
        for warning in warnings:
            report_lines.append(f"⚠ {warning}")
        report_lines.append("")

    recommendation = eval_result.get("recommendation", "")
    if recommendation:
        report_lines.append("综合建议")
        report_lines.append(recommendation)
        report_lines.append("")

    disclaimer = eval_result.get("disclaimer", "")
    if disclaimer:
        report_lines.append(disclaimer)

    return "\n".join(report_lines)


def save_to_notion_db(mentor_name: str, institution: str, result: dict):
    """将评估结果写入 Notion 数据库"""
    scores = result.get("scores", {})
    pqi_final = scores.get("PQI_final", 0)
    rating = result.get("rating", "未知")
    recommendation = result.get("recommendation", "")

    def truncate(text, max_len=1900):
        return text[:max_len] + "…" if len(text) > max_len else text

    new_page = get_notion_client().pages.create(
        parent={"database_id": NOTION_DB_ID},
        properties={
            "导师姓名": {
                "title": [{"text": {"content": mentor_name}}]
            },
            "学校/机构": {
                "rich_text": [{"text": {"content": institution}}]
            },
            "PQI总分": {"number": round(pqi_final, 3)},
            "S_学术产出": {"number": round(scores.get("S", 0), 3)},
            "P_研究生产力": {"number": round(scores.get("P", 0), 3)},
            "C_资源与支持": {"number": round(scores.get("C", 0), 3)},
            "L_实验室文化": {"number": round(scores.get("L", 0), 3)},
            "F_资金与稳定性": {"number": round(scores.get("F", 0), 3)},
            "D_毕业生去向": {"number": round(scores.get("D", 0), 3)},
            "评估状态": {"select": {"name": "已完成"}},
            "评级": {"select": {"name": rating}},
            "评估时间": {"date": {"start": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")}},
            "数据来源": {
                "rich_text": [{"text": {"content": truncate("公开网络资料（Google Scholar、学校官网、Web of Science、基金委数据库等）")}}]
            },
            "评估报告": {
                "rich_text": [{"text": {"content": truncate(recommendation)}}]
            },
        }
    )
    page_id = new_page["id"]
    notion_page_url = new_page.get("url", "")

    # 追加详细报告
    report_text = format_notion_report(result)
    get_notion_client().blocks.children.append(
        block_id=page_id,
        children=[
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "PQI 3.0 详细评估报告（Gemini + Google Search）"}}]
                }
            },
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": truncate(report_text, 1900)}}]
                }
            }
        ]
    )
    return page_id, notion_page_url


# ═══════════════════════════════════════════════════════════
#  Flask 路由
# ═══════════════════════════════════════════════════════════

@app.route("/", methods=["GET"])
def index():
    """返回前端评估页面"""
    return render_template("index.html")


@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "ok",
        "service": "PQI 3.0 导师评估服务",
        "version": "3.0.0",
        "ai_engine": "Gemini 2.5 Flash + Google Search"
    })


@app.route("/evaluate_web", methods=["POST"])
def evaluate_web():
    """网页前端调用的评估接口"""
    data = request.get_json(force=True)
    mentor_name = data.get("mentor_name", "").strip()
    institution  = data.get("institution", "").strip()
    save_to_notion = data.get("save_to_notion", True)

    if not mentor_name or not institution:
        return jsonify({"status": "error", "message": "请填写导师姓名和学校/机构"}), 400

    try:
        result = evaluate_mentor_with_gemini(mentor_name, institution)

        notion_saved = False
        notion_page_url = None

        if save_to_notion and NOTION_TOKEN and NOTION_DB_ID and NOTION_DB_ID != "placeholder_will_update":
            try:
                _, notion_page_url = save_to_notion_db(mentor_name, institution, result)
                notion_saved = True
                logger.info(f"已保存到 Notion: {mentor_name} @ {institution}")
            except Exception as ne:
                logger.warning(f"保存到 Notion 失败（不影响评估结果）: {ne}")

        return jsonify({
            "status": "ok",
            "result": result,
            "notion_saved": notion_saved,
            "notion_page_url": notion_page_url
        })

    except Exception as e:
        logger.error(f"网页评估失败: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/evaluate", methods=["POST"])
def evaluate_direct():
    """直接调用评估接口（兼容旧版 Webhook）"""
    data = request.get_json(force=True)
    mentor_name = data.get("mentor_name")
    institution = data.get("institution")

    if not mentor_name or not institution:
        return jsonify({"status": "error", "message": "缺少 mentor_name 或 institution"}), 400

    try:
        result = evaluate_mentor_with_gemini(mentor_name, institution)
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        logger.error(f"直接评估失败: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
