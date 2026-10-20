"""M3a：prompt 文件加载与版本登记。

prompt 以文件为唯一来源，修改时必须升版本号；数据库记录版本和模板内容，
每次 AI 调用都能追溯到具体 prompt 版本。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import BASE_DIR
from ...models import AiPromptVersion

PROMPTS_DIR = BASE_DIR / "prompts"
QUALITY_CHECK = ("quality_check", "v1")
logger = logging.getLogger("bajiu.ai.prompts")


@dataclass(frozen=True)
class PromptSpec:
    name: str
    version: str
    template: str
    schema_json: str
    schema: dict


@lru_cache(maxsize=16)
def load_prompt(name: str, version: str) -> PromptSpec:
    directory = PROMPTS_DIR / name
    template = (directory / f"{version}.md").read_text(encoding="utf-8")
    schema_json = (directory / f"{version}.schema.json").read_text(encoding="utf-8")
    return PromptSpec(
        name=name,
        version=version,
        template=template,
        schema_json=schema_json,
        schema=json.loads(schema_json),
    )


def render_system_prompt(spec: PromptSpec) -> str:
    schema_text = json.dumps(spec.schema, ensure_ascii=False, indent=2)
    return spec.template.replace("{{schema}}", schema_text)


def get_or_create_prompt_version(
    db: Session, spec: PromptSpec
) -> AiPromptVersion:
    row = db.scalar(
        select(AiPromptVersion).where(
            AiPromptVersion.name == spec.name,
            AiPromptVersion.version == spec.version,
        )
    )
    if row is not None:
        if row.template != spec.template or row.schema_json != spec.schema_json:
            logger.warning(
                "prompt %s %s 已存在但文件内容变化；请升级版本号，避免历史记录失真",
                spec.name,
                spec.version,
            )
        return row
    row = AiPromptVersion(
        name=spec.name,
        version=spec.version,
        template=spec.template,
        schema_json=spec.schema_json,
    )
    db.add(row)
    db.flush()
    return row
