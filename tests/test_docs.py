from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_DOCUMENTS = [
    "README.md",
    "ARCHITECTURE.md",
    "DEVELOPMENT.md",
    "docs/PERSONA_PROVIDER_CONTRACT.md",
    "docs/OPENVIKING_PERMISSION_MATRIX.md",
    "docs/OPENVIKING_CONTEXT_STRATEGY.md",
    "docs/ASTRBOT_ROUTER_DESIGN.md",
    "docs/EVAL_DESIGN.md",
    "docs/ACP_STREAMING_DESIGN.md",
    "docs/PERSONA_PLAN_B_DESIGN.md",
    "docs/SECURITY_TRUST_MODEL.md",
    "docs/ACP_BRIDGE_WIRE_SCHEMA.md",
    "docs/AIRI_EMBODIMENT_DESIGN.md",
    "docs/DEVELOPMENT_ROADMAP.md",
    "docs/HYBRID_REDUNDANCY_DESIGN.md",
    "docs/MAIBOT_REPLACEMENT_STUDY.md",
    "evals/README.md",
]

INDEX_FILES = {
    "README.md": [
        "./ARCHITECTURE.md",
        "./DEVELOPMENT.md",
        "./docs/PERSONA_PROVIDER_CONTRACT.md",
        "./docs/OPENVIKING_PERMISSION_MATRIX.md",
        "./docs/OPENVIKING_CONTEXT_STRATEGY.md",
        "./docs/ASTRBOT_ROUTER_DESIGN.md",
        "./docs/EVAL_DESIGN.md",
        "./docs/ACP_STREAMING_DESIGN.md",
        "./docs/PERSONA_PLAN_B_DESIGN.md",
        "./docs/SECURITY_TRUST_MODEL.md",
        "./docs/ACP_BRIDGE_WIRE_SCHEMA.md",
        "./docs/AIRI_EMBODIMENT_DESIGN.md",
        "./docs/DEVELOPMENT_ROADMAP.md",
        "./docs/HYBRID_REDUNDANCY_DESIGN.md",
        "./docs/MAIBOT_REPLACEMENT_STUDY.md",
    ],
    "DEVELOPMENT.md": [
        "ARCHITECTURE.md",
        "DEVELOPMENT.md",
        "docs/PERSONA_PROVIDER_CONTRACT.md",
        "docs/OPENVIKING_PERMISSION_MATRIX.md",
        "docs/OPENVIKING_CONTEXT_STRATEGY.md",
        "docs/ASTRBOT_ROUTER_DESIGN.md",
        "docs/EVAL_DESIGN.md",
        "docs/ACP_STREAMING_DESIGN.md",
        "docs/PERSONA_PLAN_B_DESIGN.md",
        "docs/SECURITY_TRUST_MODEL.md",
        "docs/ACP_BRIDGE_WIRE_SCHEMA.md",
        "docs/AIRI_EMBODIMENT_DESIGN.md",
        "docs/DEVELOPMENT_ROADMAP.md",
        "docs/HYBRID_REDUNDANCY_DESIGN.md",
        "docs/MAIBOT_REPLACEMENT_STUDY.md",
    ],
}

SECURITY_SECTIONS = [
    "信任分级",
    "组件安全职责矩阵",
    "威胁模型",
    "密钥与凭证管理",
    "数据分级与隐私",
    "沙箱与执行边界",
    "审计与可观测性",
    "事件总线 ACL",
    "故障降级安全策略",
    "安全验收清单",
]

WIRE_SCHEMA_SECTIONS = [
    "边界与原则",
    "入站：A2A `message/send`",
    "出站：A2A task",
    "ACP 调用序列",
    "错误映射",
    "流式扩展",
    "验收用例",
]

ROADMAP_SECTIONS = [
    "当前位置",
    "Phase 0：基础设施与文档基线",
    "Phase 6：评估闭环",
    "风险登记表",
    "里程碑口径",
]


def test_all_expected_documents_exist() -> None:
    missing = [
        relative_path
        for relative_path in EXPECTED_DOCUMENTS
        if not (REPO_ROOT / relative_path).is_file()
    ]
    assert not missing, f"Missing expected documents: {missing}"


def test_readme_links_all_design_documents() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for link in INDEX_FILES["README.md"]:
        normalized_link = link.removeprefix("./")
        assert f"({link})" in readme, f"README.md does not link {link}"


def test_development_lists_all_design_documents() -> None:
    development = (REPO_ROOT / "DEVELOPMENT.md").read_text(encoding="utf-8")
    for name in INDEX_FILES["DEVELOPMENT.md"]:
        assert name in development, f"DEVELOPMENT.md does not list {name}"


def test_security_document_covers_required_sections() -> None:
    security = (REPO_ROOT / "docs/SECURITY_TRUST_MODEL.md").read_text(encoding="utf-8")
    for section in SECURITY_SECTIONS:
        assert section in security, f"Security document missing section: {section}"


def test_wire_schema_covers_required_sections() -> None:
    wire_schema = (REPO_ROOT / "docs/ACP_BRIDGE_WIRE_SCHEMA.md").read_text(encoding="utf-8")
    for section in WIRE_SCHEMA_SECTIONS:
        assert section in wire_schema, f"Wire schema missing section: {section}"


def test_roadmap_covers_required_sections() -> None:
    roadmap = (REPO_ROOT / "docs/DEVELOPMENT_ROADMAP.md").read_text(encoding="utf-8")
    for section in ROADMAP_SECTIONS:
        assert section in roadmap, f"Roadmap missing section: {section}"


def test_eval_design_documents_runner_and_threshold_source() -> None:
    design = (REPO_ROOT / "docs" / "EVAL_DESIGN.md").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "evals" / "README.md").read_text(encoding="utf-8")
    thresholds = yaml.safe_load((REPO_ROOT / "evals" / "thresholds.yaml").read_text(encoding="utf-8"))

    assert "scripts/run_evals.py" in design
    assert "evals/thresholds.yaml" in design
    assert "scripts/run_evals.py" in readme
    assert thresholds["routing"]["accuracy"] == 0.90
    assert thresholds["memory"]["hit_at_5"] == 0.85


def test_roadmap_counts_current_eval_cases() -> None:
    roadmap = (REPO_ROOT / "docs/DEVELOPMENT_ROADMAP.md").read_text(encoding="utf-8")
    routing_cases = len((REPO_ROOT / "evals/routing/cases.jsonl").read_text(encoding="utf-8").splitlines())
    persona_cases = len((REPO_ROOT / "evals/persona/cases.jsonl").read_text(encoding="utf-8").splitlines())
    memory_cases = len((REPO_ROOT / "evals/memory/cases.jsonl").read_text(encoding="utf-8").splitlines())
    assert f"routing {routing_cases} / persona {persona_cases} / memory {memory_cases}" in roadmap

AIRI_SECTIONS = [
    "定位与边界",
    "A2A 请求契约",
    "emotion → 表现映射",
    "OpenViking 记忆读写",
    "事件总线联动",
    "场景联动清单",
    "MCP 接入配置片段",
    "失败降级矩阵",
    "验收标准",
]


def test_airi_design_covers_required_sections() -> None:
    airi_doc = (REPO_ROOT / "docs/AIRI_EMBODIMENT_DESIGN.md").read_text(encoding="utf-8")
    for section in AIRI_SECTIONS:
        assert section in airi_doc, f"AIRI document missing section: {section}"

CONTEXT_STRATEGY_SECTIONS = [
    "L0 / L1 / L2 分层定义与 Token 预算",
    "渐进召回状态转移流水线",
    "L0/L1 摘要生成与维护机制",
    "记忆生命周期与置信度衰减",
    "OpenViking 接入配置与 Agent Plugins 1.0 片段",
    "验收与合规清单",
]


def test_context_strategy_covers_required_sections() -> None:
    doc = (REPO_ROOT / "docs/OPENVIKING_CONTEXT_STRATEGY.md").read_text(encoding="utf-8")
    for section in CONTEXT_STRATEGY_SECTIONS:
        assert section in doc, f"Context strategy document missing section: {section}"

HYBRID_REDUNDANCY_SECTIONS = [
    "痛点与核心目标",
    "三层拓扑架构与角色划分",
    "三级运行模式与优雅降级矩阵",
    "心跳检测与状态机演进",
    "数据一致性与记忆同步设计",
    "网络互联与零信任安全架构",
    "部署实施与运维指引（脱敏模板）",
    "验收标准与测试用例",
]


def test_hybrid_redundancy_covers_required_sections() -> None:
    doc = (REPO_ROOT / "docs/HYBRID_REDUNDANCY_DESIGN.md").read_text(encoding="utf-8")
    for section in HYBRID_REDUNDANCY_SECTIONS:
        assert section in doc, f"Hybrid redundancy document missing section: {section}"

MAIBOT_REPLACEMENT_SECTIONS = [
    "现状剖析：为什么必须剔除 MaiBot？",
    "AstrBot 自身承担人格（Persona）的能力深度评测",
    "业界优秀开源人格与角色扮演项目调研",
    "三套剔除与重构落地演进方案",
    "综合选型决策与推荐路线",
]


def test_maibot_replacement_covers_required_sections() -> None:
    doc = (REPO_ROOT / "docs/MAIBOT_REPLACEMENT_STUDY.md").read_text(encoding="utf-8")
    for section in MAIBOT_REPLACEMENT_SECTIONS:
        assert section in doc, f"MaiBot replacement document missing section: {section}"
