"""确定性 ID 生成的测试（归属：P2）。

这些测试守的是**验收项 A2-7「同输入可复现」**。
如果哪天有人把 ID 换成 `uuid4()`，这里会立刻失败 —— 而不是等到演示时
发现"同一份材料跑两次，知识点 ID 全变了、diff 不出来了"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.models.ids import (
    block_id,
    chapter_id,
    describe,
    hash_bytes,
    hash_file,
    knowledge_point_id,
    material_hash_part,
    material_id,
    section_id,
)

MAT = material_id("a1b2c3d4" + "0" * 56)


def test_material_id_is_prefix_plus_first_eight_of_hash() -> None:
    full = "a1b2c3d4" + "f" * 56
    assert material_id(full) == "mat_a1b2c3d4"


def test_ids_are_deterministic_same_input_same_output() -> None:
    """★ A2-7 的核心：同一个输入跑多少次，ID 都必须一模一样。"""
    for _ in range(5):
        assert material_id("a1b2c3d4" + "0" * 56) == MAT
        assert chapter_id(MAT, 2) == "ch_a1b2c3d4_002"
        assert section_id(MAT, 2, 3) == "sec_a1b2c3d4_002_003"
        assert knowledge_point_id(MAT, 2, 3, 7) == "kp_a1b2c3d4_002_003_007"
        assert block_id(MAT, 7) == "blk_a1b2c3d4_00007"


def test_different_content_yields_different_id() -> None:
    a = material_id(hash_bytes(b"first version of the slides"))
    b = material_id(hash_bytes(b"second version of the slides"))
    assert a != b


def test_ids_are_zero_padded_so_sorting_is_stable() -> None:
    """补零不只是好看 —— 它让 ID 的字典序等于数值序，便于按 ID 排序与分片。"""
    ids = [knowledge_point_id(MAT, 0, 0, n) for n in (2, 10, 100)]
    assert ids == sorted(ids)


def test_negative_seq_is_rejected_loudly() -> None:
    """不兜底：负数序号说明上游算错了，静默修正只会把 bug 藏起来。"""
    with pytest.raises(ValueError):
        block_id(MAT, -1)


def test_non_integer_seq_is_rejected() -> None:
    with pytest.raises(TypeError):
        section_id(MAT, "2", 3)  # type: ignore[arg-type]


def test_material_hash_part_extracts_hash() -> None:
    assert material_hash_part(MAT) == "a1b2c3d4"


def test_material_hash_part_rejects_foreign_id() -> None:
    with pytest.raises(ValueError):
        material_hash_part("kp_a1b2c3d4_002_003_007")


def test_describe_explains_id_without_hitting_the_database() -> None:
    """人工校验工作台要"一眼看出这个 ID 是谁"，不该为此查库。"""
    info = describe("kp_a1b2c3d4_002_003_007")
    assert info["kind"] == "kp"
    assert info["material_hash"] == "a1b2c3d4"
    assert info["chapter_seq"] == "002"
    assert info["section_seq"] == "003"
    assert info["seq"] == "007"


def test_hash_file_matches_hash_bytes(tmp_path: Path) -> None:
    """hash_file 是流式的（大文件不整读进内存），结果必须与一次性哈希一致。"""
    payload = b"PK\x03\x04" + b"slides content" * 500
    p = tmp_path / "deck.pptx"
    p.write_bytes(payload)
    assert hash_file(p) == hash_bytes(payload)


def test_hash_file_is_stable_across_calls(tmp_path: Path) -> None:
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF-1.7 fake")
    assert hash_file(p) == hash_file(p)
