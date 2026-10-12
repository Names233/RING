from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_DOCUMENTS = [
    "README.md",
    "ARCHITECTURE.md",
    "DEVELOPMENT.md",
    "docs/PERSONA_PROVIDER_CONTRACT.md",
    "docs/OPENVIKING_PERMISSION_MATRIX.md",
    "docs/ASTRBOT_ROUTER_DESIGN.md",
    "docs/EVAL_DESIGN.md",
    "docs/ACP_STREAMING_DESIGN.md",
    "docs/PERSONA_PLAN_B_DESIGN.md",
    "docs/SECURITY_TRUST_MODEL.md",
    "docs/ACP_BRIDGE_WIRE_SCHEMA.md",
    "docs/DEVELOPMENT_ROADMAP.md",
    "evals/README.md",
]

INDEX_FILES = {
    "README.md": [
        "./ARCHITECTURE.md",
        "./DEVELOPMENT.md",
        "./docs/PERSONA_PROVIDER_CONTRACT.md",
        "./docs/OPENVIKING_PERMISSION_MATRIX.md",
        "./docs/ASTRBOT_ROUTER_DESIGN.md",
        "./docs/EVAL_DESIGN.md",
        "./docs/ACP_STREAMING_DESIGN.md",
        "./docs/PERSONA_PLAN_B_DESIGN.md",
        "./docs/SECURITY_TRUST_MODEL.md",
        "./docs/ACP_BRIDGE_WIRE_SCHEMA.md",
        "./docs/DEVELOPMENT_ROADMAP.md",
    ],
    "DEVELOPMENT.md": [
        "ARCHITECTURE.md",
        "DEVELOPMENT.md",
        "docs/PERSONA_PROVIDER_CONTRACT.md",
        "docs/OPENVIKING_PERMISSION_MATRIX.md",
        "docs/ASTRBOT_ROUTER_DESIGN.md",
        "docs/EVAL_DESIGN.md",
        "docs/ACP_STREAMING_DESIGN.md",
        "docs/PERSONA_PLAN_B_DESIGN.md",
        "docs/SECURITY_TRUST_MODEL.md",
        "docs/ACP_BRIDGE_WIRE_SCHEMA.md",
        "docs/DEVELOPMENT_ROADMAP.md",
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


def test_roadmap_counts_current_eval_cases() -> None:
    roadmap = (REPO_ROOT / "docs/DEVELOPMENT_ROADMAP.md").read_text(encoding="utf-8")
    routing_cases = len((REPO_ROOT / "evals/routing/cases.jsonl").read_text(encoding="utf-8").splitlines())
    persona_cases = len((REPO_ROOT / "evals/persona/cases.jsonl").read_text(encoding="utf-8").splitlines())
    memory_cases = len((REPO_ROOT / "evals/memory/cases.jsonl").read_text(encoding="utf-8").splitlines())
    assert f"routing {routing_cases} / persona {persona_cases} / memory {memory_cases}" in roadmap
