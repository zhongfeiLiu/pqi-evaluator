"""
PQI 3.0 导师评估后端服务
- 接收来自 Notion Webhook 的请求
- 调用 DeepSeek API 搜索并评估导师
- 通过 Notion API 将结果写回数据库
"""

import os
import json
import logging
import threading
from flask import Flask, request, jsonify, render_template
from notion_client import Client
from openai import OpenAI

# ── 日志配置 ──────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ── 环境变量 ──────────────────────────────────────────────
NOTION_TOKEN      = os.environ.get("NOTION_TOKEN", "")
NOTION_DB_ID      = os.environ.get("NOTION_DB_ID", "")
DEEPSEEK_API_KEY  = os.environ.get("DEEPSEEK_API_KEY", "")
WEBHOOK_SECRET    = os.environ.get("WEBHOOK_SECRET", "")   # 可选安全校验

# ── 客户端延迟初始化（避免启动时因环境变量缺失而崩溃）─────
_deepseek_client = None
_notion_client = None

def get_deepseek_client():
    global _deepseek_client
    if _deepseek_client is None:
        _deepseek_client = OpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", ""),
            base_url="https://api.deepseek.com"
        )
    return _deepseek_client

def get_notion_client():
    global _notion_client
    if _notion_client is None:
        _notion_client = Client(auth=os.environ.get("NOTION_TOKEN", ""))
    return _notion_client

# ═══════════════════════════════════════════════════════════
#  PQI 3.0 评估 Prompt
# ═══════════════════════════════════════════════════════════

PQI_SYSTEM_PROMPT = """你是一位专业的学术导师评估专家，擅长通过公开资料评估研究生导师的质量。
你将使用 PQI 3.0（PI Quality Index）模型对导师进行量化评估。

## PQI 3.0 核心公式
PQI = 0.35×S + 0.20×P + 0.20×C + 0.15×L + 0.10×F
PQI_final = PQI - 0.5×D

## 各维度说明与评分规则

### S：学生论文质量（权重 35%）
S = 0.7 × Mean(Top5学生论文评分) + 0.3 × Median(Top10学生论文评分)
期刊评分：Top 1% → 1.0 | Top 5% → 0.8 | Top 20% → 0.5 | 其余 → 0.2
若数据不足，根据已有信息合理估算并注明。

### P：导师科研能力（权重 20%）
P = 0.7 × P_paper + 0.3 × P_citation
P_paper = min(近5年高水平通讯作者论文数 / 10, 1)
P_citation = h-index 归一化（h-index/50，最大为1）

### C：学生去向指数（权重 20%）
C = 去向评分总和 / 入组学生人数
去向评分：顶级高校教职→1.0 | 海外Top20博后→0.8 | 国内985教职→0.7 | 国家级科研机构→0.6 | 一线大厂研究岗→0.5 | 普通企业→0.2

### L：实验室稳定度（权重 15%）
L = min(建组年数 / 10, 1)

### F：经费指数（权重 10%）
F = min(5年经费 / 500万人民币, 1)
参考：国家重大项目→1.0 | 国家重点基金→0.8 | 青年基金→0.5 | 无稳定经费→0.2

### D：淘汰率惩罚
D = (退学 + 转组 + >7年延毕人数) / 入组人数
PQI_final = PQI - 0.5×D

## 评级标准
0.85+ → 顶级实验室 | 0.70-0.85 → 优秀实验室 | 0.55-0.70 → 稳定实验室 | 0.40-0.55 → 风险实验室 | <0.40 → 高危实验室

## 你的任务
1. 基于导师姓名和所在学校，搜索并整合所有公开可获取的信息（Google Scholar、学校官网、Web of Science、实验室主页、Alumni 页面等）
2. 对每个维度进行评分，注明数据来源和置信度（高/中/低）
3. 计算最终 PQI_final 分数
4. 给出综合评级和具体建议

## 输出格式（必须严格遵守 JSON 格式）
{
  "mentor_name": "导师姓名",
  "institution": "所在学校",
  "scores": {
    "S": 0.0,
    "P": 0.0,
    "C": 0.0,
    "L": 0.0,
    "F": 0.0,
    "D": 0.0,
    "PQI": 0.0,
    "PQI_final": 0.0
  },
  "rating": "评级（如：优秀实验室）",
  "data_sources": {
    "S": "数据来源说明",
    "P": "数据来源说明",
    "C": "数据来源说明",
    "L": "数据来源说明",
    "F": "数据来源说明",
    "D": "数据来源说明"
  },
  "confidence": {
    "S": "高/中/低",
    "P": "高/中/低",
    "C": "高/中/低",
    "L": "高/中/低",
    "F": "高/中/低",
    "D": "高/中/低"
  },
  "key_findings": [
    "关键发现1",
    "关键发现2",
    "关键发现3"
  ],
  "recommendation": "综合建议（200字以内）",
  "warnings": ["风险提示1（如有）", "风险提示2（如有）"],
  "disclaimer": "数据说明：本评估基于公开网络资料，部分数据为估算值，仅供参考，建议结合面试和学长学姐反馈综合判断。"
}
"""


def evaluate_mentor_with_deepseek(mentor_name: str, institution: str) -> dict:
    """调用 DeepSeek API 对导师进行 PQI 3.0 评估"""
    user_prompt = f"""请对以下导师进行 PQI 3.0 评估：

导师姓名：{mentor_name}
所在学校/机构：{institution}

请搜索该导师的所有公开资料，包括但不限于：
- Google Scholar 主页（论文、引用、h-index）
- 学校/院系官网个人主页
- 实验室官网（学生列表、Alumni 去向）
- 基金委/科研经费公开信息
- 学术数据库（Web of Science 等）

然后严格按照 PQI 3.0 模型计算各项分数，并以指定 JSON 格式输出结果。"""

    logger.info(f"开始评估导师: {mentor_name} @ {institution}")

    response = get_deepseek_client().chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": PQI_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3,
        max_tokens=4000,
        response_format={"type": "json_object"}
    )

    raw_content = response.choices[0].message.content
    logger.info(f"DeepSeek 返回原始内容长度: {len(raw_content)}")

    result = json.loads(raw_content)
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
        f"## PQI 3.0 评估报告",
        f"**导师：** {eval_result.get('mentor_name', '')}  |  **机构：** {eval_result.get('institution', '')}",
        "",
        f"### 最终评分：{pqi_final:.3f}  →  {rating}",
        "",
        "### 各维度得分",
        f"| 维度 | 得分 | 置信度 | 数据来源 |",
        f"|------|------|--------|----------|",
        f"| S 学生论文质量 (35%) | {scores.get('S', 0):.2f} | {confidence.get('S', '-')} | {data_sources.get('S', '-')} |",
        f"| P 导师科研能力 (20%) | {scores.get('P', 0):.2f} | {confidence.get('P', '-')} | {data_sources.get('P', '-')} |",
        f"| C 学生去向 (20%) | {scores.get('C', 0):.2f} | {confidence.get('C', '-')} | {data_sources.get('C', '-')} |",
        f"| L 实验室稳定度 (15%) | {scores.get('L', 0):.2f} | {confidence.get('L', '-')} | {data_sources.get('L', '-')} |",
        f"| F 经费指数 (10%) | {scores.get('F', 0):.2f} | {confidence.get('F', '-')} | {data_sources.get('F', '-')} |",
        f"| D 淘汰率惩罚 | {scores.get('D', 0):.2f} | {confidence.get('D', '-')} | {data_sources.get('D', '-')} |",
        f"| **PQI (原始)** | **{scores.get('PQI', 0):.3f}** | - | - |",
        f"| **PQI_final** | **{pqi_final:.3f}** | - | - |",
        "",
    ]

    if key_findings:
        report_lines.append("### 关键发现")
        for finding in key_findings:
            report_lines.append(f"- {finding}")
        report_lines.append("")

    if warnings:
        report_lines.append("### ⚠️ 风险提示")
        for warning in warnings:
            report_lines.append(f"- {warning}")
        report_lines.append("")

    recommendation = eval_result.get("recommendation", "")
    if recommendation:
        report_lines.append("### 综合建议")
        report_lines.append(recommendation)
        report_lines.append("")

    disclaimer = eval_result.get("disclaimer", "")
    if disclaimer:
        report_lines.append("---")
        report_lines.append(f"*{disclaimer}*")

    return "\n".join(report_lines)


def update_notion_page(page_id: str, eval_result: dict):
    """将评估结果更新到 Notion 数据库页面"""
    scores = eval_result.get("scores", {})
    pqi_final = scores.get("PQI_final", 0)
    rating = eval_result.get("rating", "未知")
    recommendation = eval_result.get("recommendation", "")
    report_text = format_notion_report(eval_result)

    # 截断过长文本（Notion rich_text 限制 2000 字符）
    def truncate(text, max_len=1900):
        return text[:max_len] + "…" if len(text) > max_len else text

    properties = {
        "PQI分数": {
            "number": round(pqi_final, 3)
        },
        "评级": {
            "select": {"name": rating}
        },
        "综合建议": {
            "rich_text": [{"text": {"content": truncate(recommendation)}}]
        },
        "评估状态": {
            "select": {"name": "已完成"}
        },
        "S分": {"number": round(scores.get("S", 0), 3)},
        "P分": {"number": round(scores.get("P", 0), 3)},
        "C分": {"number": round(scores.get("C", 0), 3)},
        "L分": {"number": round(scores.get("L", 0), 3)},
        "F分": {"number": round(scores.get("F", 0), 3)},
        "D惩罚": {"number": round(scores.get("D", 0), 3)},
    }

    get_notion_client().pages.update(page_id=page_id, properties=properties)
    logger.info(f"已更新 Notion 页面属性: {page_id}")

    # 将详细报告追加为页面内容
    get_notion_client().blocks.children.append(
        block_id=page_id,
        children=[
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "PQI 3.0 详细评估报告"}}]
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
    logger.info(f"已追加详细报告到 Notion 页面: {page_id}")


def process_evaluation(page_id: str, mentor_name: str, institution: str):
    """后台线程：执行评估并写回 Notion"""
    try:
        # 先将状态更新为"评估中"
        get_notion_client().pages.update(
            page_id=page_id,
            properties={
                "评估状态": {"select": {"name": "评估中"}}
            }
        )

        # 调用 DeepSeek 评估
        eval_result = evaluate_mentor_with_deepseek(mentor_name, institution)

        # 写回 Notion
        update_notion_page(page_id, eval_result)
        logger.info(f"评估完成: {mentor_name} @ {institution}, PQI_final={eval_result['scores']['PQI_final']:.3f}")

    except Exception as e:
        logger.error(f"评估失败: {mentor_name} @ {institution}, 错误: {e}", exc_info=True)
        try:
            get_notion_client().pages.update(
                page_id=page_id,
                properties={
                    "评估状态": {"select": {"name": "评估失败"}},
                    "综合建议": {
                        "rich_text": [{"text": {"content": f"评估过程中发生错误：{str(e)[:200]}"}}]
                    }
                }
            )
        except Exception as e2:
            logger.error(f"更新错误状态失败: {e2}")


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
        "version": "2.0.0"
    })


@app.route("/webhook", methods=["POST"])
def notion_webhook():
    """接收来自 Notion Button 的 Webhook 请求"""
    try:
        data = request.get_json(force=True)
        logger.info(f"收到 Webhook 请求: {json.dumps(data, ensure_ascii=False)[:500]}")

        # ── 从 Notion Webhook payload 中提取数据 ──────────────
        # Notion Button Webhook 发送的是数据库页面属性
        page_id = None
        mentor_name = None
        institution = None

        # 尝试从不同的 payload 结构中提取
        if "data" in data:
            # Notion Database Automation Webhook 格式
            page_data = data.get("data", {})
            page_id = page_data.get("id") or data.get("page_id")
            props = page_data.get("properties", {})
        elif "properties" in data:
            # 直接包含 properties
            page_id = data.get("id") or data.get("page_id")
            props = data.get("properties", {})
        else:
            # 简化格式（直接传递字段）
            page_id = data.get("page_id") or data.get("id")
            props = data

        # 提取导师姓名
        if "导师姓名" in props:
            title_prop = props["导师姓名"]
            if isinstance(title_prop, dict):
                title_arr = title_prop.get("title", [])
                if title_arr:
                    mentor_name = title_arr[0].get("plain_text", "")
            elif isinstance(title_prop, str):
                mentor_name = title_prop

        # 提取学校
        if "学校" in props:
            school_prop = props["学校"]
            if isinstance(school_prop, dict):
                rich_text = school_prop.get("rich_text", [])
                if rich_text:
                    institution = rich_text[0].get("plain_text", "")
                else:
                    # 可能是 select 类型
                    select_val = school_prop.get("select", {})
                    if select_val:
                        institution = select_val.get("name", "")
            elif isinstance(school_prop, str):
                institution = school_prop

        # 兜底：直接从顶层取
        if not mentor_name:
            mentor_name = data.get("mentor_name") or data.get("导师姓名")
        if not institution:
            institution = data.get("institution") or data.get("学校")
        if not page_id:
            page_id = data.get("page_id")

        logger.info(f"解析结果 - page_id: {page_id}, 导师: {mentor_name}, 学校: {institution}")

        if not mentor_name or not institution:
            return jsonify({
                "status": "error",
                "message": "缺少必要参数：导师姓名 或 学校"
            }), 400

        if not page_id:
            return jsonify({
                "status": "error",
                "message": "缺少 page_id，无法写回 Notion"
            }), 400

        # ── 在后台线程中执行评估（避免 Webhook 超时）─────────
        thread = threading.Thread(
            target=process_evaluation,
            args=(page_id, mentor_name, institution),
            daemon=True
        )
        thread.start()

        return jsonify({
            "status": "accepted",
            "message": f"已开始评估 {mentor_name} @ {institution}，结果将在 1-2 分钟内写回 Notion。"
        }), 202

    except Exception as e:
        logger.error(f"Webhook 处理失败: {e}", exc_info=True)
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route("/evaluate", methods=["POST"])
def evaluate_direct():
    """直接调用评估接口（用于测试，不需要 Notion page_id）"""
    data = request.get_json(force=True)
    mentor_name = data.get("mentor_name")
    institution = data.get("institution")

    if not mentor_name or not institution:
        return jsonify({"status": "error", "message": "缺少 mentor_name 或 institution"}), 400

    try:
        result = evaluate_mentor_with_deepseek(mentor_name, institution)
        return jsonify({"status": "ok", "result": result})
    except Exception as e:
        logger.error(f"直接评估失败: {e}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/evaluate_web", methods=["POST"])
def evaluate_web():
    """网页前端调用的评估接口：评估完成后可选写入 Notion"""
    data = request.get_json(force=True)
    mentor_name = data.get("mentor_name", "").strip()
    institution  = data.get("institution", "").strip()
    save_to_notion = data.get("save_to_notion", True)

    if not mentor_name or not institution:
        return jsonify({"status": "error", "message": "请填写导师姓名和学校/机构"}), 400

    try:
        # 调用 DeepSeek 评估
        result = evaluate_mentor_with_deepseek(mentor_name, institution)

        notion_saved = False
        notion_page_url = None

        # 可选：写入 Notion 数据库
        if save_to_notion and NOTION_TOKEN and NOTION_DB_ID and NOTION_DB_ID != "placeholder_will_update":
            try:
                scores = result.get("scores", {})
                pqi_final = scores.get("PQI_final", 0)
                rating = result.get("rating", "未知")
                recommendation = result.get("recommendation", "")

                def truncate(text, max_len=1900):
                    return text[:max_len] + "…" if len(text) > max_len else text

                # 创建新页面（数据库中新增一行）
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
                        "综合建议": {
                            "rich_text": [{"text": {"content": truncate(recommendation)}}]
                        },
                    }
                )
                page_id = new_page["id"]
                notion_page_url = new_page.get("url", "")

                # 追加详细报告到页面内容
                report_text = format_notion_report(result)
                get_notion_client().blocks.children.append(
                    block_id=page_id,
                    children=[
                        {
                            "object": "block",
                            "type": "heading_2",
                            "heading_2": {
                                "rich_text": [{"type": "text", "text": {"content": "PQI 3.0 详细评估报告"}}]
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
