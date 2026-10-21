"""封面（Preview.webp）生成的单元测试。

覆盖 2026-08-21 生产事故暴露的三类缺陷：
1. 内层重试预算超出外层 wait_for，导致重试永远跑不完
2. a9fe4f2 重构漏改，pipeline 仍在检查旧版小写 preview.webp
3. metadata.json 被多个写入方相互全量覆盖，字段丢失
"""
import json
import re
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

backend_dir = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(backend_dir))

from generate_preview_images import (  # noqa: E402
    _extract_image_bytes,
    _request_image,
    env_int,
    update_metadata,
)


class FakeResponse:
    """最小化的 requests.Response 替身。"""

    def __init__(self, status_code: int, payload=None, text: str = "", content: bytes = b""):
        self.status_code = status_code
        self._payload = payload
        self.text = text
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("响应不是合法 JSON")
        return self._payload


def _ok_payload(b64: str = "aGVsbG8="):
    return {"data": [{"b64_json": b64}]}


@pytest.fixture(autouse=True)
def _preview_env(monkeypatch):
    """固定环境变量，并把退避设为 0 以免拖慢测试。"""
    monkeypatch.setenv("GPTsAPI_KEY", "test-key")
    monkeypatch.setenv("GPTsAPI_BASE", "https://example.invalid/v1")
    monkeypatch.setenv("GPTsAPI_IMAGE_MODEL", "test-model")
    monkeypatch.setenv("PREVIEW_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("PREVIEW_RETRY_BACKOFF_SECONDS", "0")
    monkeypatch.setenv("PREVIEW_MIN_ATTEMPT_SECONDS", "1")
    monkeypatch.setenv("PREVIEW_REQUEST_TIMEOUT_SECONDS", "180")
    monkeypatch.setenv("PREVIEW_BACKUP_TOTAL_TIMEOUT_SECONDS", "270")
    # 隔离真实 .env 中的备用模型配置，避免测试受环境值影响（需要备用配置的测试自行 setenv）
    for _name in (
        "BACKUP_MODEL_API_KEY",
        "BACKUP_MODEL_BASE_URL",
        "BACKUP_MODEL_NAME",
        "BACKUP_IMAGE_MODEL_API_KEY",
        "BACKUP_IMAGE_MODEL_BASE_URL",
        "BACKUP_IMAGE_MODEL_NAME",
    ):
        monkeypatch.setenv(_name, "")


# ---------------------------------------------------------------- 重试与预算


def test_retries_on_5xx_then_succeeds():
    """504 应触发重试，第三次 200 时正常返回图片字节。"""
    responses = [
        FakeResponse(504, text="gateway timeout"),
        FakeResponse(504, text="gateway timeout"),
        FakeResponse(200, payload=_ok_payload()),
    ]
    with patch("generate_preview_images.requests.post", side_effect=responses) as post:
        result = _request_image("p", deadline=time.monotonic() + 120)

    assert result == b"hello"
    assert post.call_count == 3


def test_request_timeout_shrinks_to_remaining_budget():
    """单次请求超时必须收缩到剩余预算之内，不能用固定的 180 秒。

    这是根因 1 的核心：内层若按固定 180s×5 次编排，总预算会达到 920s，
    远超外层 wait_for 的 300s，重试永远跑不完。
    """
    with patch(
        "generate_preview_images.requests.post",
        return_value=FakeResponse(200, payload=_ok_payload()),
    ) as post:
        _request_image("p", deadline=time.monotonic() + 30)

    passed_timeout = post.call_args.kwargs["timeout"]
    assert passed_timeout <= 30, "超时未收缩到剩余预算之内"
    assert passed_timeout > 25, "超时收缩得过于激进"


def test_stops_when_budget_exhausted():
    """预算已耗尽时应干净退出，且不再发起任何请求。"""
    with patch("generate_preview_images.requests.post") as post:
        with pytest.raises(RuntimeError, match="预算耗尽"):
            _request_image("p", deadline=time.monotonic() - 1)

    post.assert_not_called()


def test_respects_max_attempts():
    """持续 5xx 时不应超过 PREVIEW_MAX_ATTEMPTS 次请求。"""
    with patch(
        "generate_preview_images.requests.post",
        return_value=FakeResponse(500, text="boom"),
    ) as post:
        with pytest.raises(RuntimeError, match="重试已达上限"):
            _request_image("p", deadline=time.monotonic() + 120)

    assert post.call_count == 3


def test_switches_to_backup_image_model_on_timeout(monkeypatch):
    """默认模型超时后应切换到专用备用封面生图模型，而不是一直用默认模型重试。"""
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_API_KEY", "backup-key")
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_BASE_URL", "https://backup.invalid/v1")
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_NAME", "backup-image-model")

    with patch(
        "generate_preview_images.requests.post",
        side_effect=requests.Timeout("read timed out"),
    ) as post:
        with pytest.raises(RuntimeError, match="重试已达上限"):
            _request_image("p", deadline=time.monotonic() + 30)

    # 第二次请求必须已切换到备用封面生图模型；备用重试计数独立重置后，
    # 备用自身可用满 PREVIEW_MAX_ATTEMPTS=3 次（1 次默认 + 3 次备用 = 4 次请求）
    assert post.call_count == 4
    backup_json = post.call_args_list[1].kwargs["json"]
    assert backup_json["model"] == "backup-image-model"
    assert post.call_args_list[1].kwargs["headers"]["Authorization"] == "Bearer backup-key"


def test_backup_image_model_succeeds_after_primary_timeout(monkeypatch):
    """默认模型超时后，备用封面生图模型应接手并成功返回图片（管理后台遇险场景）。"""
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_API_KEY", "backup-key")
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_BASE_URL", "https://backup.invalid/v1")
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_NAME", "backup-image-model")

    responses = [requests.Timeout("read timed out"), FakeResponse(200, payload=_ok_payload())]
    with patch("generate_preview_images.requests.post", side_effect=responses) as post:
        result = _request_image("p", deadline=time.monotonic() + 30)

    assert result == b"hello"
    assert post.call_count == 2
    assert post.call_args_list[1].kwargs["json"]["model"] == "backup-image-model"


def test_switches_to_backup_image_model_on_524(monkeypatch):
    """网关返回 HTTP 524（网关超时）时应切换备用封面生图模型，而非仅按 5xx 重试。"""
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_API_KEY", "backup-key")
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_BASE_URL", "https://backup.invalid/v1")
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_NAME", "backup-image-model")

    responses = [FakeResponse(524, text="gateway timeout"), FakeResponse(200, payload=_ok_payload())]
    with patch("generate_preview_images.requests.post", side_effect=responses) as post:
        result = _request_image("p", deadline=time.monotonic() + 120)

    assert result == b"hello"
    assert post.call_count == 2
    assert post.call_args_list[1].kwargs["json"]["model"] == "backup-image-model"


def test_is_timeout_error_recognizes_gateway_524():
    """openai SDK 抛出的 524（网关超时）InternalServerError 应被判定为超时类错误，
    否则动画/智能体/分类等路径在默认模型 524 时不会切换备用模型。"""
    import httpx
    from openai import InternalServerError

    from kimi_config import is_timeout_error

    request = httpx.Request("POST", "https://kuaipao.pro/v1/chat/completions")
    response = httpx.Response(524, request=request)
    exc = InternalServerError("Gateway Timeout", response=response, body=None)
    assert is_timeout_error(exc) is True


def test_default_model_not_shrunk_when_backup_configured(monkeypatch):
    """备用模型预算独立后，默认模型不再为备用预留而被压缩单次超时。"""
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_API_KEY", "backup-key")
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_BASE_URL", "https://backup.invalid/v1")
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_NAME", "backup-image-model")

    with patch(
        "generate_preview_images.requests.post",
        return_value=FakeResponse(200, payload=_ok_payload()),
    ) as post:
        _request_image("p", deadline=time.monotonic() + 120)

    passed_timeout = post.call_args.kwargs["timeout"]
    assert passed_timeout > 60, "默认模型单次超时不应为备用模型预留而被压缩"


def test_backup_gets_independent_full_budget(monkeypatch):
    """默认模型超时切换备用后，备用模型应获得独立满额预算（deadline 重置）。

    默认模型只剩 30s 预算；旧共享预算逻辑下备用只能用残余时间（单次超时 ≤30s），
    现在备用 deadline 重置为 PREVIEW_BACKUP_TOTAL_TIMEOUT_SECONDS=270，
    单次请求超时恢复到 PREVIEW_REQUEST_TIMEOUT_SECONDS=180 的上限。
    """
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_API_KEY", "backup-key")
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_BASE_URL", "https://backup.invalid/v1")
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_NAME", "backup-image-model")

    responses = [requests.Timeout("read timed out"), FakeResponse(200, payload=_ok_payload())]
    with patch("generate_preview_images.requests.post", side_effect=responses) as post:
        _request_image("p", deadline=time.monotonic() + 30)

    assert post.call_count == 2
    # 默认模型：单次超时收缩到剩余 30s 预算之内
    assert post.call_args_list[0].kwargs["timeout"] <= 30
    # 备用模型：独立满额预算，单次超时恢复 180s 上限
    assert post.call_args_list[1].kwargs["timeout"] == 180


def test_preview_backup_extra_seconds_counts_configured_levels(monkeypatch):
    """外层兜底应按已配置的备用模型级数累加独立预算。"""
    from generate_preview_images import preview_backup_extra_seconds

    monkeypatch.setenv("PREVIEW_BACKUP_TOTAL_TIMEOUT_SECONDS", "270")
    assert preview_backup_extra_seconds() == 0  # fixture 已清空备用配置

    monkeypatch.setenv("BACKUP_IMAGE_MODEL_API_KEY", "k1")
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_BASE_URL", "https://backup.invalid/v1")
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_NAME", "m1")
    assert preview_backup_extra_seconds() == 270

    monkeypatch.setenv("BACKUP_MODEL_API_KEY", "k2")
    monkeypatch.setenv("BACKUP_MODEL_BASE_URL", "https://common.invalid/v1")
    monkeypatch.setenv("BACKUP_MODEL_NAME", "m2")
    assert preview_backup_extra_seconds() == 540


def test_two_level_backup_chain(monkeypatch):
    """专用封面备用失败后，应继续切到动画共用备用模型（第二级兜底）。"""
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_API_KEY", "backup-key")
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_BASE_URL", "https://backup.invalid/v1")
    monkeypatch.setenv("BACKUP_IMAGE_MODEL_NAME", "backup-image-model")
    monkeypatch.setenv("BACKUP_MODEL_API_KEY", "common-key")
    monkeypatch.setenv("BACKUP_MODEL_BASE_URL", "https://common.invalid/v1")
    monkeypatch.setenv("BACKUP_MODEL_NAME", "common-model")

    responses = [
        requests.Timeout("read timed out"),  # 默认模型超时
        requests.Timeout("read timed out"),  # 专用封面备用超时
        FakeResponse(200, payload=_ok_payload()),  # 动画共用备用成功
    ]
    with patch("generate_preview_images.requests.post", side_effect=responses) as post:
        result = _request_image("p", deadline=time.monotonic() + 120)

    assert result == b"hello"
    assert post.call_count == 3
    assert post.call_args_list[0].kwargs["json"]["model"] == "test-model"  # 默认
    assert post.call_args_list[1].kwargs["json"]["model"] == "backup-image-model"  # 第一级
    assert post.call_args_list[2].kwargs["json"]["model"] == "common-model"  # 第二级


@pytest.mark.parametrize("status", [400, 401, 403])
def test_4xx_fails_immediately_without_retry(status):
    """4xx 重试无意义，应只发一次请求即失败。

    400（内容审核拦截）刻意不做降级 prompt 重试：封面必须由 2.0 提示词生成。
    这条同时充当守卫——若日后有人把降级逻辑加回来，400 会变成 2 次请求，测试立刻失败。
    """
    with patch(
        "generate_preview_images.requests.post",
        return_value=FakeResponse(status, text="rejected"),
    ) as post:
        with pytest.raises(RuntimeError, match=f"HTTP {status}"):
            _request_image("p", deadline=time.monotonic() + 120)

    assert post.call_count == 1


def test_only_one_prompt_builder_exists():
    """代码中只应存在 2.0 一条提示词构造函数，杜绝生成非 2.0 风格封面。"""
    import generate_preview_images as module

    builders = [n for n in dir(module) if n.startswith("build_") and n.endswith("prompt")]
    assert builders == ["build_image_prompt"], f"出现了额外的提示词构造函数: {builders}"


# ---------------------------------------------------------------- 响应解析


def test_empty_data_raises_runtime_error_not_index_error():
    """接口返回 200 但 data 为空数组时，原代码会抛裸 IndexError。"""
    response = FakeResponse(200, payload={"data": []})
    with pytest.raises(RuntimeError, match="空 data"):
        _extract_image_bytes(response, deadline=time.monotonic() + 60)


def test_missing_b64_and_url_raises_runtime_error():
    """既无 b64_json 也无 url 时，原代码会抛裸 KeyError。"""
    response = FakeResponse(200, payload={"data": [{"revised_prompt": "x"}]})
    with pytest.raises(RuntimeError, match="既无 b64_json 也无 url"):
        _extract_image_bytes(response, deadline=time.monotonic() + 60)


def test_non_json_response_raises_runtime_error():
    response = FakeResponse(200, payload=None, text="<html>502</html>")
    with pytest.raises(RuntimeError, match="非 JSON"):
        _extract_image_bytes(response, deadline=time.monotonic() + 60)


def test_download_failure_does_not_reach_image_decoder():
    """下载返回 403 时必须拦住，否则错误页正文会喂给 Image.open。"""
    response = FakeResponse(200, payload={"data": [{"url": "https://example.invalid/a.png"}]})
    with patch(
        "generate_preview_images.requests.get",
        return_value=FakeResponse(403, text="forbidden"),
    ):
        with pytest.raises(RuntimeError, match="下载图片失败 HTTP 403"):
            _extract_image_bytes(response, deadline=time.monotonic() + 60)


# ---------------------------------------------------------------- metadata 合并


def test_update_metadata_preserves_existing_fields(tmp_path):
    """封面字段与教学元数据分两次写入，彼此都不应被抹掉。"""
    update_metadata(tmp_path, {"preview_image": "Preview.webp"})
    update_metadata(tmp_path, {"title": "鸡兔同笼", "knowledge_tags": {"main_tag": "方程"}})

    meta = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert meta["preview_image"] == "Preview.webp"
    assert meta["title"] == "鸡兔同笼"
    assert meta["knowledge_tags"]["main_tag"] == "方程"


def test_update_metadata_survives_reversed_write_order(tmp_path):
    """迟到的封面写入不得丢掉先写的 knowledge_tags。"""
    update_metadata(tmp_path, {"title": "鸡兔同笼", "knowledge_tags": {"main_tag": "方程"}})
    update_metadata(tmp_path, {"preview_image": "Preview.webp"})

    meta = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert meta["knowledge_tags"]["main_tag"] == "方程"
    assert meta["preview_image"] == "Preview.webp"


def test_update_metadata_rebuilds_corrupt_file(tmp_path):
    (tmp_path / "metadata.json").write_text("{ 半截 JSON", encoding="utf-8")
    update_metadata(tmp_path, {"preview_image": "Preview.webp"})

    meta = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert meta == {"preview_image": "Preview.webp"}


def test_update_metadata_leaves_no_temp_file(tmp_path):
    update_metadata(tmp_path, {"a": 1})
    assert list(tmp_path.glob("*.tmp")) == []


# ---------------------------------------------------------------- 环境变量解析


def test_env_int_falls_back_on_invalid_value(monkeypatch):
    monkeypatch.setenv("PREVIEW_MAX_ATTEMPTS", "not-a-number")
    assert env_int("PREVIEW_MAX_ATTEMPTS", 3) == 3


def test_env_int_reads_valid_value(monkeypatch):
    monkeypatch.setenv("PREVIEW_MAX_ATTEMPTS", "7")
    assert env_int("PREVIEW_MAX_ATTEMPTS", 3) == 7


# ---------------------------------------------------------------- 命名回归守卫


def test_pipeline_does_not_reintroduce_lowercase_preview_filename():
    """守住 a9fe4f2 那次"重构漏改"不再复发。

    磁盘上封面统一为大写 Preview.webp。pipeline.py 中允许残留的小写字面量
    只有两处"大写优先、小写兜底"的历史兼容 elif（用于识别重命名迁移之前的
    旧数据），每处各含路径与赋值两个字面量，合计 4 个：

      - execute() 里的预览图检测（581bb6c 加入）
      - _save_teaching_content() 里的数据库赋值（a9fe4f2 保留）

    多于 4 个说明又有新代码写回了旧命名。这类 bug 在 Windows 上测不出来
    （NTFS 大小写不敏感，小写路径照样命中大写文件），只能靠源码断言兜住。
    """
    source = (backend_dir / "pipeline.py").read_text(encoding="utf-8")
    occurrences = re.findall(r'"preview\.webp"', source)
    assert len(occurrences) == 4, (
        f"pipeline.py 中小写 \"preview.webp\" 出现 {len(occurrences)} 次，预期 4 次"
        "（仅限两处历史兼容分支）。新增代码请使用大写 Preview.webp。"
    )
