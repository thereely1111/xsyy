#!/usr/bin/env python3
"""
邀请码绑定同步脚本

功能：
1. 确保每个用户都有专属邀请码（缺失则自动生成）
2. 确保每个用户都有邀请进度记录 invite_progress
3. 根据 invite_relations 邀请关系表重新统计每个邀请人的"成功邀请人数"（修复计数漂移）
4. 输出"未绑定邀请人"的用户清单（系统未记录其注册时使用的邀请码）

用法（在服务器 backend 目录执行）：
    python sync_invite_bindings.py
"""
import secrets
import sys
from pathlib import Path

from sqlalchemy import func

backend_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(backend_dir))

from database import SessionLocal
from database.models import InviteProgress, InviteRelation, User

LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ"


def generate_unique_invite_code(existing_codes: set) -> str:
    """生成不与现有码冲突的专属邀请码（4位大写字母+4位数字）"""
    for _ in range(200):
        code = "".join(secrets.choice(LETTERS) for _ in range(4)) + f"{secrets.randbelow(10000):04d}"
        if code not in existing_codes:
            existing_codes.add(code)
            return code
    raise RuntimeError("邀请码生成失败")


def main() -> None:
    print("=" * 60)
    print("邀请码绑定同步")
    print("=" * 60)

    db = SessionLocal()
    try:
        users = db.query(User).all()
        existing_codes = {u.invite_code for u in users if u.invite_code}
        print(f"\n共 {len(users)} 个用户")

        # 1. 补全缺失的邀请码
        missing = [u for u in users if not u.invite_code]
        for u in missing:
            u.invite_code = generate_unique_invite_code(existing_codes)
        if missing:
            print(f"✓ 已为 {len(missing)} 个缺少邀请码的用户生成专属邀请码")
        else:
            print("✓ 所有用户都已有专属邀请码")

        # 2. 确保每个用户都有 invite_progress 进度记录
        user_ids = [u.user_id for u in users]
        progress_ids = {
            row[0]
            for row in db.query(InviteProgress.user_id)
            .filter(InviteProgress.user_id.in_(user_ids))
            .all()
        }
        need_progress = [uid for uid in user_ids if uid not in progress_ids]
        for uid in need_progress:
            db.add(InviteProgress(user_id=uid, invited_count=0, claimed_targets=[]))
        if need_progress:
            print(f"✓ 已为 {len(need_progress)} 个用户补建邀请进度记录")
        else:
            print("✓ 所有用户都已有邀请进度记录")

        # 3. 按 invite_relations 实际数据重新统计邀请人数
        counts = dict(
            db.query(InviteRelation.inviter_user_id, func.count(InviteRelation.id))
            .group_by(InviteRelation.inviter_user_id)
            .all()
        )
        progress_rows = db.query(InviteProgress).filter(InviteProgress.user_id.in_(user_ids)).all()
        fixed = 0
        for p in progress_rows:
            real = int(counts.get(p.user_id, 0) or 0)
            if int(p.invited_count or 0) != real:
                p.invited_count = real
                fixed += 1
        if fixed:
            print(f"✓ 已修正 {fixed} 个用户的成功邀请人数（与邀请关系表对齐）")
        else:
            print("✓ 所有用户的成功邀请人数与邀请关系表一致")

        db.commit()

        # 4. 输出未绑定邀请人的用户
        bound_invited_ids = {row[0] for row in db.query(InviteRelation.invited_user_id).all()}
        unbound = [u for u in users if u.user_id not in bound_invited_ids]
        print(f"\n未绑定邀请人的用户（无邀请关系记录）: {len(unbound)} 个")
        for u in unbound:
            print(f"  - {u.username}  (user_id={u.user_id})")
        if unbound:
            print("\n说明：这些用户注册时未使用他人邀请码，或使用记录未入库。")
            print("由于系统没有保存'注册时使用的邀请码'，无法自动回填绑定关系；")
            print("如有明确的使用记录（如前端 localStorage 的 user_invite_code），可按 (用户名/手机号, 邀请码) 对照后补充绑定。")

        print("\n完成")
    finally:
        db.close()


if __name__ == "__main__":
    main()
