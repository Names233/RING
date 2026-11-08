#!/usr/bin/env python3
"""MaiBot OpenViking 读写钩子安装器（幂等、可回滚）。

用途
----
把 openviking_injector.py / openviking_writer.py 两个新增模块复制进 MaiBot 的
site-packages，并在三处挂载点插入最小改动；--uninstall 可把三处挂载点还原并删除
新增模块，恢复到未打补丁的状态。

默认行为是 dry-run：只打印将做的改动，不写任何文件；必须显式给出 --apply 才落盘。

安全约束
--------
* 只允许改动 src/maisaka/memory/ 下的两个新增文件，以及
  src/maisaka/reasoning_engine.py、src/maisaka/runtime.py、src/runtime.py 三个挂载点，
  其它路径一律不碰。
* 三处挂载点采用「精确锚点整块替换」，锚点必须唯一命中；上游版本变化导致锚点缺失时
  直接报冲突并放弃写入，不做模糊匹配、不做猜测式插入。
* 写文件前先备份原始文件到 <mai-root>/backup/openviking-hook-<时间戳>/。
* 密钥只从环境变量读取（OPENVIKING_API_KEY / OPENVIKING_API_KEY_FILE），
  终端输出一律打码；写出的 openviking.json 权限设为 0600。

用法
----
    python install.py --dry-run
    python install.py --apply --site-packages /opt/ring/toolenv/maibot/lib/python3.13/site-packages
    python install.py --uninstall --apply --site-packages /opt/ring/toolenv/maibot/lib/python3.13/site-packages
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

PATCH_ROOT = Path(__file__).resolve().parent
CONFIG_SAMPLE_PATH = PATCH_ROOT / "config-sample.json"
CONFIG_FILENAME = "openviking.json"
BACKUP_DIRNAME_PREFIX = "openviking-hook-"
ENV_API_KEY = "OPENVIKING_API_KEY"
ENV_API_KEY_FILE = "OPENVIKING_API_KEY_FILE"
ENV_SITE_PACKAGES = "MAIBOT_SITE_PACKAGES"
ENV_MAI_ROOT = "MAIBOT_ROOT"
MASKED = "***"
PLACEHOLDER_SITE = "<site-packages>"
DEFAULT_MAI_ROOT = "/opt/ring/maibot"
WRITE_STATE_FILENAME = "openviking_write_state.json"


# ---------------------------------------------------------------------------
# 新增模块（整文件复制）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NewModule:
    """一个需要整文件落到 site-packages 的新增模块。"""

    source: Path
    target: str
    note: str


NEW_MODULES: tuple[NewModule, ...] = (
    NewModule(
        source=PATCH_ROOT / "openviking_injector.py",
        target="src/maisaka/memory/openviking_injector.py",
        note="读侧：把 OpenViking 长期记忆注入 planner 上下文",
    ),
    NewModule(
        source=PATCH_ROOT / "openviking_writer.py",
        target="src/maisaka/memory/openviking_writer.py",
        note="写侧：60s 轮询增量写入，20 条阈值 / 900s 空闲显式 commit",
    ),
)


# ---------------------------------------------------------------------------
# 三处挂载点：精确锚点的整块替换
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Edit:
    """一个可逆的最小文本替换。old 与 new 必须互不为子串。"""

    key: str
    label: str
    old: str
    new: str


@dataclass(frozen=True)
class Segment:
    """一处挂载点（一个目标文件内的若干处替换）。"""

    key: str
    target: str
    title: str
    anchor: str
    edits: tuple[Edit, ...]


# --- 第一处：src/maisaka/reasoning_engine.py ------------------------------

_R_IMPORT_OLD = """\
from src.maisaka.memory.heuristic_injector import heuristic_memory_injector
from src.maisaka.memory.image_injector import image_memory_injector
"""

_R_IMPORT_NEW = """\
from src.maisaka.memory.heuristic_injector import heuristic_memory_injector
from src.maisaka.memory.openviking_injector import openviking_memory_injector
from src.maisaka.memory.image_injector import image_memory_injector
"""

_R_INJECT_OLD = """\
        pending = {"启发式记忆", "人物画像", "图片记忆"}
        if round_text is not None:
            self._runtime._update_stage_status("组织上下文", "正在准备：启发式记忆、人物画像、图片记忆", round_text=round_text)
"""

_R_INJECT_NEW = """\
        async def build_openviking_memory_message() -> str:
            try:
                return await openviking_memory_injector.build_injection_message(
                    session_id=str(self._runtime.session_id or ""),
                )
            except Exception as exc:
                logger.debug(f"{self._runtime.log_prefix} OpenViking 记忆拉起失败，已跳过: {exc}")
                return ""

        pending = {"启发式记忆", "人物画像", "图片记忆", "OpenViking记忆"}
        if round_text is not None:
            self._runtime._update_stage_status("组织上下文", "正在准备：启发式记忆、OpenViking记忆、人物画像、图片记忆", round_text=round_text)
"""

_R_REMAINING_OLD = """\
                    remaining = "、".join(item for item in ("启发式记忆", "人物画像", "图片记忆") if item in pending)
"""

_R_REMAINING_NEW = """\
                    remaining = "、".join(item for item in ("启发式记忆", "OpenViking记忆", "人物画像", "图片记忆") if item in pending)
"""

_R_GATHER_OLD = """\
        heuristic_memory_message, profile_messages, image_memory_message = await asyncio.gather(
            measure_injection("启发式记忆", build_heuristic_memory_message),
            measure_injection("人物画像", build_profile_messages),
            measure_injection("图片记忆", build_image_memory_message),
        )
"""

_R_GATHER_NEW = """\
        heuristic_memory_message, profile_messages, image_memory_message, openviking_memory_message = await asyncio.gather(
            measure_injection("启发式记忆", build_heuristic_memory_message),
            measure_injection("人物画像", build_profile_messages),
            measure_injection("图片记忆", build_image_memory_message),
            measure_injection("OpenViking记忆", build_openviking_memory_message),
        )
"""

_R_APPEND_OLD = """\
        if heuristic_memory_message:
            injected_messages.append(heuristic_memory_message)
        injected_messages.extend(profile_messages)
"""

_R_APPEND_NEW = """\
        if heuristic_memory_message:
            injected_messages.append(heuristic_memory_message)
        if openviking_memory_message:
            injected_messages.append(openviking_memory_message)
        injected_messages.extend(profile_messages)
"""

# --- 第二处：src/maisaka/runtime.py --------------------------------------

_RT_START_OLD = """\
        self._ensure_background_tasks_running()
        self._schedule_message_turn()
"""

_RT_START_NEW = """\
        self._ensure_background_tasks_running()
        try:
            from src.maisaka.memory.openviking_writer import openviking_memory_writer

            await openviking_memory_writer.ensure_started()
        except Exception as exc:  # 写入侧异常不得影响运行时启动
            logger.debug(f"{self.log_prefix} OpenViking 写入任务启动失败: {exc}")
        self._schedule_message_turn()
"""

# --- 第三处：src/runtime.py ----------------------------------------------

_RTM_MAIN_OLD = """\
            _run_until_complete(loop, initialize_task)
            main_tasks = loop.create_task(main_system.schedule_tasks())
"""

_RTM_MAIN_NEW = """\
            _run_until_complete(loop, initialize_task)
            # 启动 OpenViking 长期记忆写入后台任务；失败不影响主流程
            try:
                from src.maisaka.memory.openviking_writer import openviking_memory_writer

                _start_writer = loop.create_task(openviking_memory_writer.ensure_started())
                _run_until_complete(loop, _start_writer)
            except Exception as _writer_exc:
                logger.warning(f"OpenViking 写入任务启动失败: {_writer_exc}")
            main_tasks = loop.create_task(main_system.schedule_tasks())
"""


SEGMENTS: tuple[Segment, ...] = (
    Segment(
        key="mount-1",
        target="src/maisaka/reasoning_engine.py",
        title="读侧注入口挂到 planner 上下文聚合（asyncio.gather 第 4 路）",
        anchor=(
            "模块级 import 区（上游第 82-85 行，heuristic_injector 导入之后）；"
            "以及 _build_planner_injected_user_messages（上游第 280 行定义）内，"
            "上游第 320-348 行的 pending 集合、阶段提示语、asyncio.gather 与注入结果拼接"
        ),
        edits=(
            Edit(key="R1", label="import 区新增 openviking_injector 导入", old=_R_IMPORT_OLD, new=_R_IMPORT_NEW),
            Edit(
                key="R2",
                label="新增 build_openviking_memory_message 协程，并把 OpenViking记忆 计入 pending",
                old=_R_INJECT_OLD,
                new=_R_INJECT_NEW,
            ),
            Edit(key="R3", label="等待提示语的剩余项加入 OpenViking记忆", old=_R_REMAINING_OLD, new=_R_REMAINING_NEW),
            Edit(key="R4", label="asyncio.gather 增加第 4 路注入器", old=_R_GATHER_OLD, new=_R_GATHER_NEW),
            Edit(key="R5", label="注入结果追加到 injected_messages", old=_R_APPEND_OLD, new=_R_APPEND_NEW),
        ),
    ),
    Segment(
        key="mount-2",
        target="src/maisaka/runtime.py",
        title="Maisaka 运行时启动时拉起写入侧后台协程",
        anchor=(
            "MaisakaHeartFlowChatting.start()（上游第 275 行定义）内，"
            "上游第 286 行 self._ensure_background_tasks_running() 之后、"
            "self._schedule_message_turn() 之前"
        ),
        edits=(
            Edit(
                key="RT1",
                label="start() 内 await openviking_memory_writer.ensure_started()",
                old=_RT_START_OLD,
                new=_RT_START_NEW,
            ),
        ),
    ),
    Segment(
        key="mount-3",
        target="src/runtime.py",
        title="进程主入口在主循环里启动写入任务（兜底）",
        anchor=(
            "def raw_main()（上游第 490 行定义）内，"
            "上游第 531 行 _run_until_complete(loop, initialize_task) 之后、"
            "main_tasks = loop.create_task(main_system.schedule_tasks()) 之前"
        ),
        edits=(
            Edit(
                key="RTM1",
                label="loop.create_task(ensure_started()) 并等其完成",
                old=_RTM_MAIN_OLD,
                new=_RTM_MAIN_NEW,
            ),
        ),
    ),
)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------


def _emit(text: str = "") -> None:
    """统一输出，规避 Windows 控制台编码问题。"""

    print(text)


def _init_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _mask(value: str) -> str:
    """密钥打码：只保留长度信息，绝不回显内容。"""

    text = (value or "").strip()
    if not text:
        return "(空)"
    return f"{MASKED}(len={len(text)})"


def _read_text(path: Path) -> str:
    """以 UTF-8 读取，保持行尾原样（不做换行翻译）。"""

    return path.read_bytes().decode("utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _unified_diff(target: str, old: str, new: str, limit: int = 200) -> list[str]:
    lines = list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=f"a/{target}",
            tofile=f"b/{target}",
            lineterm="",
            n=3,
        )
    )
    if len(lines) > limit:
        lines = lines[:limit] + [f"... (diff 截断，共 {len(lines)} 行)"]
    return lines


# ---------------------------------------------------------------------------
# 计划与执行
# ---------------------------------------------------------------------------


@dataclass
class SegmentPlan:
    segment: Segment
    path: Path
    action: str  # apply / already / conflict / missing / unknown
    old_text: str = ""
    new_text: str = ""
    problems: list[str] = field(default_factory=list)


@dataclass
class ModulePlan:
    module: NewModule
    path: Path
    action: str  # write / overwrite / identical / delete / absent / unknown
    source_bytes: bytes | None = None


def _apply_edits(text: str, edits: tuple[Edit, ...], *, reverse: bool) -> tuple[str, list[str], bool]:
    """按顺序应用（或反向应用）整块替换。

    返回 (新文本, 问题列表, 是否已经是目标状态)。
    """

    problems: list[str] = []
    already = 0
    ordered = tuple(reversed(edits)) if reverse else edits
    for edit in ordered:
        src, dst = (edit.new, edit.old) if reverse else (edit.old, edit.new)
        count_src = text.count(src)
        count_dst = text.count(dst)
        if count_dst == 1 and count_src == 0:
            already += 1
            continue
        if count_src == 0:
            head = src.splitlines()[0].strip() if src.splitlines() else ""
            problems.append(f"{edit.key} 「{edit.label}」锚点未命中，首行: {head}")
            continue
        if count_src > 1:
            problems.append(f"{edit.key} 「{edit.label}」锚点命中 {count_src} 次，拒绝修改")
            continue
        text = text.replace(src, dst, 1)
    return text, problems, already == len(edits)


def plan_segments(site_packages: Path | None, *, uninstall: bool) -> list[SegmentPlan]:
    plans: list[SegmentPlan] = []
    for segment in SEGMENTS:
        if site_packages is None:
            path = Path(PLACEHOLDER_SITE) / segment.target
            plans.append(SegmentPlan(segment=segment, path=path, action="unknown"))
            continue
        path = site_packages / segment.target
        if not path.is_file():
            plans.append(
                SegmentPlan(
                    segment=segment,
                    path=path,
                    action="missing",
                    problems=[f"目标文件不存在: {path}"],
                )
            )
            continue
        old_text = _read_text(path)
        new_text, problems, already = _apply_edits(old_text, segment.edits, reverse=uninstall)
        if problems:
            action = "conflict"
        elif already:
            action = "already"
        else:
            action = "apply"
        plans.append(
            SegmentPlan(
                segment=segment,
                path=path,
                action=action,
                old_text=old_text,
                new_text=new_text,
                problems=problems,
            )
        )
    return plans


def plan_modules(site_packages: Path | None, *, uninstall: bool) -> list[ModulePlan]:
    plans: list[ModulePlan] = []
    for module in NEW_MODULES:
        if site_packages is None:
            plans.append(ModulePlan(module=module, path=Path(PLACEHOLDER_SITE) / module.target, action="unknown"))
            continue
        path = site_packages / module.target
        source_bytes: bytes | None = None
        if uninstall:
            action = "delete" if path.is_file() else "absent"
        else:
            if module.source.is_file():
                source_bytes = module.source.read_bytes()
            action = "overwrite" if path.is_file() else "write"
            if path.is_file() and source_bytes is not None and path.read_bytes() == source_bytes:
                action = "identical"
        plans.append(ModulePlan(module=module, path=path, action=action, source_bytes=source_bytes))
    return plans


def build_config_payload() -> tuple[dict[str, object], list[str]]:
    """从脱敏样例生成待写配置；密钥只来自环境变量。"""

    warnings: list[str] = []
    if not CONFIG_SAMPLE_PATH.is_file():
        raise SystemExit(f"缺少配置样例: {CONFIG_SAMPLE_PATH}")
    payload = json.loads(CONFIG_SAMPLE_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"配置样例不是 JSON 对象: {CONFIG_SAMPLE_PATH}")

    api_key = os.environ.get(ENV_API_KEY, "").strip()
    api_key_file = os.environ.get(ENV_API_KEY_FILE, "").strip()
    if api_key:
        payload["api_key"] = api_key
    else:
        payload["api_key"] = ""
        warnings.append(
            f"未设置环境变量 {ENV_API_KEY}：openviking.json 的 api_key 留空，运行时会退回读取 api_key_file。"
        )
    if api_key_file:
        payload["api_key_file"] = api_key_file
    if not str(payload.get("api_key") or "") and not str(payload.get("api_key_file") or ""):
        warnings.append("api_key 与 api_key_file 都为空，读写两侧都会跳过 OpenViking 调用。")
    return payload, warnings


def _resolve_site_packages(value: str | None) -> Path | None:
    if value:
        return Path(value).expanduser()
    env_value = os.environ.get(ENV_SITE_PACKAGES, "").strip()
    if env_value:
        return Path(env_value).expanduser()
    return None


def _backup_paths(items: list[tuple[Path, str]], base: Path) -> None:
    """按相对路径备份，避免同名文件（如两处 runtime.py）互相覆盖。"""

    for path, relative in items:
        if not path.is_file():
            continue
        destination = base / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def _syntax_check(paths: list[Path]) -> list[str]:
    """用 compile() 做语法检查，避免写出 __pycache__。"""

    problems: list[str] = []
    for path in paths:
        if not path.is_file():
            continue
        try:
            compile(_read_text(path), str(path), "exec")
        except SyntaxError as exc:
            problems.append(f"语法错误 {path}:{exc.lineno}: {exc.msg}")
        except Exception as exc:  # pragma: no cover - 兜底
            problems.append(f"读取失败 {path}: {exc!r}")
    return problems


def _remove_pycache_entry(path: Path) -> None:
    """删除某个模块对应的 .pyc，避免残留字节码干扰。"""

    cache_dir = path.parent / "__pycache__"
    if not cache_dir.is_dir():
        return
    for candidate in cache_dir.glob(f"{path.stem}.*.pyc"):
        try:
            candidate.unlink()
        except OSError:
            pass


def _chmod_600(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# 打印
# ---------------------------------------------------------------------------


_ACTION_TEXT = {
    "apply": "将修改",
    "already": "已是目标状态，跳过",
    "conflict": "存在冲突，跳过",
    "missing": "目标文件缺失",
    "unknown": "待确认（未给出 site-packages）",
    "write": "将新建",
    "overwrite": "将覆盖（内容与补丁不同）",
    "identical": "内容一致，跳过",
    "delete": "将删除",
    "absent": "不存在，跳过",
    "skip-existing": "已存在且内容不同，保留原文件（--force-config 可覆盖）",
}


def _action_text(action: str, uninstall: bool) -> str:
    """回滚模式下把「将修改」表述为「将还原」。"""

    if action == "apply" and uninstall:
        return "将还原"
    return _ACTION_TEXT.get(action, action)


def print_plan(
    *,
    site_packages: Path | None,
    uninstall: bool,
    segment_plans: list[SegmentPlan],
    module_plans: list[ModulePlan],
    config_path: Path | None,
    config_action: str,
    config_payload: dict[str, object],
    config_warnings: list[str],
    show_diff: bool,
) -> None:
    mode = "回滚（卸载）" if uninstall else "安装"
    _emit("=" * 78)
    _emit(f"MaiBot OpenViking 钩子 — {mode}计划")
    _emit("=" * 78)
    _emit(f"site-packages : {site_packages if site_packages is not None else PLACEHOLDER_SITE}")
    _emit("")

    for index, plan in enumerate(segment_plans, start=1):
        segment = plan.segment
        _emit(f"[挂载点 {index}/{len(segment_plans)}] {segment.target} — {segment.title}")
        _emit(f"    状态: {_action_text(plan.action, uninstall)}")
        _emit(f"    锚点: {segment.anchor}")
        for edit in segment.edits:
            _emit(f"      - {edit.key}: {edit.label}")
        for problem in plan.problems:
            _emit(f"    ! {problem}")
        if show_diff and plan.action == "apply" and plan.new_text != plan.old_text:
            for line in _unified_diff(segment.target, plan.old_text, plan.new_text):
                _emit(f"    {line}")
        _emit("")

    _emit(f"[新增模块] {len(module_plans)} 个整文件")
    for plan in module_plans:
        _emit(f"    - {plan.module.target}: {_ACTION_TEXT.get(plan.action, plan.action)}")
        _emit(f"      说明: {plan.module.note}")
    _emit("")

    _emit("[配置文件]")
    if config_path is None:
        _emit("    未处理 openviking.json")
    else:
        _emit(f"    - {config_path}: {_ACTION_TEXT.get(config_action, config_action)}（权限 0600）")
        _emit(f"      api_key       = {_mask(str(config_payload.get('api_key') or ''))}")
        _emit(f"      api_key_file  = {config_payload.get('api_key_file') or '(未设置)'}")
        _emit(f"      enabled       = {config_payload.get('enabled')}")
        _emit(f"      write_enabled = {config_payload.get('write_enabled')}")
    for warning in config_warnings:
        _emit(f"    ! {warning}")
    _emit("")


def print_result(
    *,
    segment_plans: list[SegmentPlan],
    module_plans: list[ModulePlan],
    config_path: Path | None,
    config_action: str,
    backup_dir: Path | None,
    uninstall: bool,
) -> None:
    _emit("=" * 78)
    _emit("执行结果")
    _emit("=" * 78)
    for plan in segment_plans:
        _emit(f"  {plan.segment.target}: {_action_text(plan.action, uninstall)}")
    for plan in module_plans:
        _emit(f"  {plan.module.target}: {_action_text(plan.action, uninstall)}")
    if config_path is not None:
        _emit(f"  {config_path}: {_action_text(config_action, uninstall)}")
    if backup_dir is not None:
        _emit(f"  备份目录: {backup_dir}")
    _emit("")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MaiBot OpenViking 读写钩子安装/回滚器（幂等，默认 dry-run）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--site-packages",
        default=None,
        help=f"目标 site-packages 目录；也可用环境变量 {ENV_SITE_PACKAGES}",
    )
    parser.add_argument(
        "--mai-root",
        default=None,
        help=f"MaiBot 实例根目录（用于 data/ 与 backup/）；也可用 {ENV_MAI_ROOT}，默认 {DEFAULT_MAI_ROOT}",
    )
    parser.add_argument("--apply", action="store_true", help="真正写文件；不带此参数时等同 --dry-run")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划（默认行为）")
    parser.add_argument("--uninstall", action="store_true", help="回滚：移除三处挂载并删除新增模块")
    parser.add_argument("--force-config", action="store_true", help="即使 openviking.json 已存在也重写")
    parser.add_argument("--backup-dir", default=None, help="备份目录；默认 <mai-root>/backup/openviking-hook-<时间戳>")
    parser.add_argument("--no-config", action="store_true", help="完全不处理 openviking.json")
    parser.add_argument("--no-diff", action="store_true", help="dry-run 时不打印 diff 预览")
    return parser


def main(argv: list[str] | None = None) -> int:
    _init_stdout()
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.apply and args.dry_run:
        parser.error("--apply 与 --dry-run 不能同时给出")

    apply = bool(args.apply) and not args.dry_run
    uninstall = bool(args.uninstall)
    site_packages = _resolve_site_packages(args.site_packages)

    if apply and site_packages is None:
        _emit(f"错误: 写入模式必须给出 --site-packages 或环境变量 {ENV_SITE_PACKAGES}")
        return 2
    if apply and site_packages is not None and not site_packages.is_dir():
        _emit(f"错误: site-packages 目录不存在: {site_packages}")
        return 2

    mai_root_raw = args.mai_root or os.environ.get(ENV_MAI_ROOT, "").strip() or DEFAULT_MAI_ROOT
    mai_root = Path(mai_root_raw).expanduser()

    segment_plans = plan_segments(site_packages, uninstall=uninstall)
    module_plans = plan_modules(site_packages, uninstall=uninstall)

    config_path: Path | None = None
    config_action = "skip"
    config_payload: dict[str, object] = {}
    config_warnings: list[str] = []
    if uninstall:
        config_warnings.append(
            f"回滚不会删除 {mai_root / 'data' / CONFIG_FILENAME} 与写入游标 "
            f"{mai_root / 'data' / WRITE_STATE_FILENAME}，如不再使用请手工删除。"
        )
    elif not args.no_config:
        config_payload, config_warnings = build_config_payload()
        config_path = mai_root / "data" / CONFIG_FILENAME
        if config_path.is_file() and not args.force_config:
            config_action = "identical" if _config_matches(config_path, config_payload) else "skip-existing"
        else:
            config_action = "write"

    print_plan(
        site_packages=site_packages,
        uninstall=uninstall,
        segment_plans=segment_plans,
        module_plans=module_plans,
        config_path=config_path,
        config_action=config_action,
        config_payload=config_payload,
        config_warnings=config_warnings,
        show_diff=not args.no_diff,
    )

    conflicts = [plan for plan in segment_plans if plan.action in {"conflict", "missing"}]
    if not apply:
        _emit("dry-run 结束：未写入任何文件。确认无误后加 --apply 执行。")
        if conflicts:
            _emit(f"注意: {len(conflicts)} 处挂载点存在冲突，--apply 会被拒绝。")
            return 1
        return 0

    if conflicts:
        _emit(f"拒绝执行: {len(conflicts)} 处挂载点存在冲突，未写入任何文件。")
        return 1

    if args.backup_dir:
        backup_dir = Path(args.backup_dir).expanduser()
    else:
        backup_dir = mai_root / "backup" / f"{BACKUP_DIRNAME_PREFIX}{_timestamp()}"
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        _emit(f"错误: 无法创建备份目录 {backup_dir}: {exc}")
        return 1

    _backup_paths(
        [(plan.path, plan.segment.target) for plan in segment_plans if plan.action == "apply"],
        backup_dir,
    )

    try:
        for plan in segment_plans:
            if plan.action != "apply":
                continue
            _write_text(plan.path, plan.new_text)

        for plan in module_plans:
            if plan.action in {"write", "overwrite"}:
                if plan.source_bytes is None:
                    _emit(f"错误: 缺少源文件 {plan.module.source}")
                    return 1
                plan.path.parent.mkdir(parents=True, exist_ok=True)
                plan.path.write_bytes(plan.source_bytes)
            elif plan.action == "delete":
                plan.path.unlink(missing_ok=True)

        if config_path is not None and config_action == "write":
            _write_text(config_path, json.dumps(config_payload, ensure_ascii=False, indent=2) + "\n")
            _chmod_600(config_path)
    except Exception as exc:
        _emit(f"错误: 写入过程中失败: {exc!r}")
        return 1

    for plan in module_plans:
        if plan.path.is_file():
            _remove_pycache_entry(plan.path)

    syntax_problems = _syntax_check([plan.path for plan in segment_plans])
    syntax_problems += _syntax_check([plan.path for plan in module_plans if plan.path.is_file()])

    print_result(
        segment_plans=segment_plans,
        module_plans=module_plans,
        config_path=config_path,
        config_action=config_action,
        backup_dir=backup_dir,
        uninstall=uninstall,
    )
    if syntax_problems:
        for problem in syntax_problems:
            _emit(f"  ! {problem}")
        _emit("语法检查未通过，请用备份目录回滚。")
        return 1
    _emit("语法检查通过。重启 MaiBot 后生效。")
    return 0


def _config_matches(path: Path, payload: dict[str, object]) -> bool:
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    return existing == payload


if __name__ == "__main__":
    raise SystemExit(main())
