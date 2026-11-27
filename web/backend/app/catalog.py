"""Read the Watcher Skill manifests to build the detection catalog."""

from __future__ import annotations

import sys
import threading
from pathlib import Path

from . import config

LANGUAGE_META = {
    "java": ("Java", "面向 JVM 后端与 Android 的 Java 源码审查"),
    "python": ("Python", "Python 脚本、服务与数据处理代码审查"),
    "php": ("PHP", "PHP Web 应用与脚本源码审查"),
    "c": ("C/C++", "C 与 C++ 源码的内存、边界、资源与并发缺陷审查"),
    "agent_skill": ("Agent Skill", "Agent Skill 包的提示词注入、恶意代码、权限与供应链审查"),
}

DEFECT_LABELS = {
    "CWE-476": "空指针解引用",
    "CWE-369": "除零",
    "CWE-772": "资源未释放",
    "CWE-89": "SQL 注入",
    "CWE-78": "命令注入",
    "CWE-22": "路径穿越",
    "CWE-79": "跨站脚本 XSS",
    "CWE-98": "文件包含",
    "CWE-94": "代码注入",
    "CWE-470": "不安全反射",
    "CWE-390": "异常处理不当",
    "CWE-248": "未捕获异常",
    "CWE-704": "类型转换错误",
    "CWE-457": "使用未初始化变量",
    "CWE-665": "初始化不当",
    "CWE-362": "竞态条件",
    "CWE-1333": "正则拒绝服务",
    "CWE-95": "eval 注入",
    "CWE-113": "响应头注入",
    "CWE-502": "不安全反序列化",
    "CWE-377": "不安全临时文件",
    "CWE-327": "弱加密算法",
    "CWE-295": "证书校验缺失",
    "CWE-611": "XML 外部实体",
    "CWE-676": "危险函数调用",
    "CWE-400": "资源耗尽",
    "CWE-190": "整数溢出",
    "CWE-798": "硬编码凭据",
    "CWE-547": "硬编码安全常量",
    "CWE-617": "可达断言",
    "CWE-1336": "模板注入",
    "CWE-125": "越界读取",
    "CWE-401": "内存泄漏",
    "CWE-606": "未检查循环条件",
    "CWE-197": "数值截断",
    "CWE-191": "整数下溢",
    "Prompt Injection": "提示词注入",
    "Malicious Code": "恶意代码",
    "Excessive Permissions": "权限过大",
    "Secret Exposure": "密钥泄露",
    "Supply Chain": "供应链风险",
    "Validation": "元数据校验",
}

_lock = threading.Lock()
_catalog: dict | None = None
_error = ""
_detector_path = ""


def ensure_framework_path() -> None:
    src = str(config.FRAMEWORK_SRC)
    if src not in sys.path:
        sys.path.insert(0, src)


def _load() -> dict:
    global _catalog, _error, _detector_path

    ensure_framework_path()
    languages: list[dict] = []
    error = ""
    try:
        import detector
        from detector.discovery import skill_root
        from detector.skills import SkillRegistry
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        return {
            "languages": [],
            "framework": {
                "path": str(config.FRAMEWORK_DIR),
                "available": False,
                "detector_path": "",
                "error": f"无法导入 Watcher 框架：{type(exc).__name__}: {exc}",
            },
        }

    _detector_path = str(Path(detector.__file__).resolve())
    try:
        # Warm the heavier workflow imports so the first scan is not delayed.
        import detector.agent_executor  # noqa: F401
        import detector.executor  # noqa: F401
        import detector.model  # noqa: F401
        import detector.protocols  # noqa: F401
        import detector.services  # noqa: F401
        import detector.sources  # noqa: F401
        import detector.workflow  # noqa: F401
    except Exception:
        pass
    root = skill_root()
    manifests = sorted(root.glob("*/manifest.json"))
    if not manifests:
        error = f"未在 {root} 下找到任何 Skill 清单"

    for path in manifests:
        try:
            skill = SkillRegistry().register(path.parent)
        except Exception:
            continue
        language = skill.manifest.languages[0]
        if language not in LANGUAGE_META:
            continue
        extensions = skill.manifest.file_extensions.get(language, [])
        name, description = LANGUAGE_META[language]
        languages.append(
            {
                "code": language,
                "name": name,
                "description": description,
                "skill_id": skill.manifest.id,
                "skill_version": skill.manifest.version,
                "extensions": extensions,
                "defect_types": [
                    {"code": code, "label": DEFECT_LABELS.get(code, code)}
                    for code in skill.manifest.defect_types
                ],
            }
        )

    languages.sort(key=lambda item: list(LANGUAGE_META).index(item["code"]))
    if not languages and not error:
        error = "没有可用的语言 Skill，请检查框架的 skills 目录"

    return {
        "languages": languages,
        "framework": {
            "path": str(config.FRAMEWORK_DIR),
            "available": bool(languages),
            "detector_path": _detector_path,
            "error": error,
        },
    }


def load_catalog(force: bool = False) -> dict:
    global _catalog
    with _lock:
        if _catalog is None or force:
            _catalog = _load()
        return _catalog


def get_catalog() -> dict:
    return load_catalog()


def get_language(code: str) -> dict | None:
    for item in load_catalog()["languages"]:
        if item["code"] == code:
            return item
    return None


def defect_label(code: str) -> str:
    return DEFECT_LABELS.get(code, code)
