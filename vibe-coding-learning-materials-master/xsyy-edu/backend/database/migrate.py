"""
数据迁移脚本
从 JSON 文件迁移数据到 MySQL 数据库
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# 添加父目录到路径
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from database import SessionLocal, init_db, User, VerificationCode, Teaching, Comment, CommentLike, TeachingLike, Favorite
from sqlalchemy.exc import IntegrityError
from utils.embedding_utils import get_question_embedding
from utils.vector_db import (
    get_chroma_client,
    get_chroma_collection,
    add_teaching_embedding,
)


def migrate_users(db):
    """迁移用户数据从 users.json 到数据库"""
    users_file = backend_dir / "users" / "users.json"
    
    if not users_file.exists():
        print(f"用户文件不存在: {users_file}，跳过用户迁移")
        return 0
    
    print("开始迁移用户数据...")
    with open(users_file, "r", encoding="utf-8") as f:
        users_data = json.load(f)
    
    migrated_count = 0
    skipped_count = 0
    
    for username, user_data in users_data.items():
        try:
            # 检查用户是否已存在
            existing_user = db.query(User).filter(User.user_id == user_data.get("user_id")).first()
            if existing_user:
                print(f"用户已存在，跳过: {username}")
                skipped_count += 1
                continue
            
            # 解析创建时间
            created_at = None
            if user_data.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(user_data["created_at"])
                except:
                    created_at = datetime.utcnow()
            else:
                created_at = datetime.utcnow()
            
            # 解析重置 token 过期时间
            reset_token_expiry = None
            if user_data.get("reset_token_expiry"):
                try:
                    reset_token_expiry = datetime.fromisoformat(user_data["reset_token_expiry"])
                except:
                    pass
            
            new_user = User(
                user_id=user_data.get("user_id"),
                username=user_data.get("username", username),
                phone=user_data.get("phone"),
                password_hash=user_data.get("password_hash", ""),
                created_at=created_at,
                reset_token=user_data.get("reset_token"),
                reset_token_expiry=reset_token_expiry
            )
            db.add(new_user)
            db.commit()
            migrated_count += 1
            print(f"✓ 迁移用户: {username}")
        except IntegrityError as e:
            db.rollback()
            print(f"✗ 用户迁移失败（可能已存在）: {username} - {e}")
            skipped_count += 1
        except Exception as e:
            db.rollback()
            print(f"✗ 用户迁移失败: {username} - {e}")
            skipped_count += 1
    
    print(f"用户迁移完成: 成功 {migrated_count} 个，跳过 {skipped_count} 个")
    return migrated_count


def migrate_teachings(db, storage_dir: Path, force_update: bool = False):
    """迁移教学内容数据从 storage/*/metadata.json 到数据库。
    
    Args:
        db: 数据库会话
        storage_dir: storage 目录路径
        force_update: 若为 True，则已存在的 teaching 也会从 metadata.json 更新字段
    """
    if not storage_dir.exists():
        print(f"存储目录不存在: {storage_dir}，跳过教学内容迁移")
        return 0
    
    print("开始迁移教学内容数据...")
    migrated_count = 0
    updated_count = 0
    skipped_count = 0
    
    for task_dir in storage_dir.iterdir():
        if not task_dir.is_dir():
            continue
        
        metadata_path = task_dir / "metadata.json"
        if not metadata_path.exists():
            continue
        
        task_id = task_dir.name
        
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
            
            # 检查是否已存在
            existing_teaching = db.query(Teaching).filter(Teaching.task_id == task_id).first()
            
            # 解析生成时间
            generated_at = None
            if metadata.get("generated_at"):
                try:
                    generated_at = datetime.fromisoformat(metadata["generated_at"])
                except:
                    generated_at = datetime.utcnow()
            else:
                generated_at = datetime.utcnow()
            
            # 提取标签信息，优先使用新 knowledge_tags，旧 tags 仅作兼容回退
            knowledge_tags = metadata.get("knowledge_tags")
            if isinstance(knowledge_tags, list):
                knowledge_tags = knowledge_tags[0] if knowledge_tags else None
            if isinstance(knowledge_tags, dict) and knowledge_tags.get("main_tag"):
                main_tag = knowledge_tags.get("main_tag")
                sub_tags = knowledge_tags.get("sub_tags", []) if isinstance(knowledge_tags.get("sub_tags", []), list) else []
            else:
                tags = metadata.get("tags", {})
                main_tag = tags.get("main_tag") if isinstance(tags, dict) else None
                sub_tags = tags.get("sub_tags", []) if isinstance(tags, dict) else None
                knowledge_tags = None
            
            if existing_teaching and force_update:
                existing_teaching.question = metadata.get("question", "") or existing_teaching.question
                existing_teaching.prompt = metadata.get("prompt")
                existing_teaching.title = metadata.get("title")
                existing_teaching.is_math_problem = metadata.get("is_math_problem", existing_teaching.is_math_problem)
                existing_teaching.main_tag = main_tag
                existing_teaching.sub_tags = sub_tags
                existing_teaching.knowledge_tags = knowledge_tags
                existing_teaching.reasoning = metadata.get("reasoning")
                existing_teaching.generated_at = generated_at or existing_teaching.generated_at
                existing_teaching.input_file = metadata.get("input_file")
                existing_teaching.teaching_html_file = metadata.get("teaching_html_file", "teaching.html")
                existing_teaching.preview_image = metadata.get("preview_image")
                db.commit()
                updated_count += 1
                print(f"✓ 更新教学内容: {task_id}")
            elif existing_teaching and not force_update:
                print(f"教学内容已存在，跳过: {task_id}")
                skipped_count += 1
                continue
            else:
                new_teaching = Teaching(
                    task_id=task_id,
                    question=metadata.get("question", ""),
                    prompt=metadata.get("prompt", ""),
                    title=metadata.get("title"),
                    is_math_problem=metadata.get("is_math_problem", True),
                    main_tag=main_tag,
                    sub_tags=sub_tags,
                    knowledge_tags=knowledge_tags,
                    reasoning=metadata.get("reasoning"),
                    generated_at=generated_at,
                    input_file=metadata.get("input_file"),
                    teaching_html_file=metadata.get("teaching_html_file", "teaching.html"),
                    preview_image=metadata.get("preview_image")
                )
                db.add(new_teaching)
                db.commit()
                migrated_count += 1
                print(f"✓ 迁移教学内容: {task_id}")
            
            # 迁移评论
            comments = metadata.get("comments", [])
            if comments:
                migrate_comments_for_teaching(db, task_id, comments)
            
            # 迁移点赞
            liked_users = metadata.get("liked_users", [])
            if liked_users:
                migrate_likes_for_teaching(db, task_id, liked_users)
            
        except IntegrityError as e:
            db.rollback()
            print(f"✗ 教学内容迁移失败（可能已存在）: {task_id} - {e}")
            skipped_count += 1
        except Exception as e:
            db.rollback()
            print(f"✗ 教学内容迁移失败: {task_id} - {e}")
            skipped_count += 1
    
    print(f"教学内容迁移完成: 新增 {migrated_count} 个，更新 {updated_count} 个，跳过 {skipped_count} 个")
    return migrated_count


def migrate_comments_for_teaching(db, task_id: str, comments: List[Dict]):
    """迁移评论数据"""
    migrated_count = 0
    
    for comment_data in comments:
        try:
            comment_id = comment_data.get("comment_id")
            if not comment_id:
                continue
            
            # 检查是否已存在
            existing_comment = db.query(Comment).filter(Comment.comment_id == comment_id).first()
            if existing_comment:
                continue
            
            # 解析创建时间
            created_at = None
            if comment_data.get("created_at"):
                try:
                    created_at = datetime.fromisoformat(comment_data["created_at"])
                except:
                    created_at = datetime.utcnow()
            else:
                created_at = datetime.utcnow()
            
            new_comment = Comment(
                comment_id=comment_id,
                task_id=task_id,
                user_id=comment_data.get("user_id", ""),
                username=comment_data.get("username", "用户"),
                content=comment_data.get("content", ""),
                created_at=created_at,
                likes=comment_data.get("likes", 0)
            )
            db.add(new_comment)
            db.commit()
            migrated_count += 1
            
            # 迁移评论点赞
            liked_users = comment_data.get("liked_users", [])
            if liked_users:
                migrate_comment_likes(db, comment_id, liked_users)
            
        except IntegrityError:
            db.rollback()
        except Exception as e:
            db.rollback()
            print(f"  评论迁移失败: {comment_data.get('comment_id')} - {e}")
    
    if migrated_count > 0:
        print(f"  ✓ 迁移了 {migrated_count} 条评论")


def migrate_comment_likes(db, comment_id: str, liked_users: List[str]):
    """迁移评论点赞数据"""
    for user_id in liked_users:
        try:
            existing_like = db.query(CommentLike).filter(
                CommentLike.comment_id == comment_id,
                CommentLike.user_id == user_id
            ).first()
            if existing_like:
                continue
            
            new_like = CommentLike(comment_id=comment_id, user_id=user_id)
            db.add(new_like)
            db.commit()
        except IntegrityError:
            db.rollback()
        except Exception:
            db.rollback()


def migrate_likes_for_teaching(db, task_id: str, liked_users: List[str]):
    """迁移教学内容点赞数据"""
    migrated_count = 0
    
    for user_id in liked_users:
        try:
            existing_like = db.query(TeachingLike).filter(
                TeachingLike.task_id == task_id,
                TeachingLike.user_id == user_id
            ).first()
            if existing_like:
                continue
            
            new_like = TeachingLike(task_id=task_id, user_id=user_id)
            db.add(new_like)
            db.commit()
            migrated_count += 1
        except IntegrityError:
            db.rollback()
        except Exception:
            db.rollback()
    
    if migrated_count > 0:
        print(f"  ✓ 迁移了 {migrated_count} 个点赞")


def migrate_favorites(db, users_file: Path):
    """迁移用户收藏数据"""
    if not users_file.exists():
        return 0
    
    print("开始迁移用户收藏数据...")
    with open(users_file, "r", encoding="utf-8") as f:
        users_data = json.load(f)
    
    migrated_count = 0
    
    for username, user_data in users_data.items():
        user_id = user_data.get("user_id")
        if not user_id:
            continue
        
        favorites = user_data.get("favorites", [])
        if not favorites:
            continue
        
        for task_id in favorites:
            try:
                existing_favorite = db.query(Favorite).filter(
                    Favorite.user_id == user_id,
                    Favorite.task_id == task_id
                ).first()
                if existing_favorite:
                    continue
                
                new_favorite = Favorite(
                    user_id=user_id,
                    task_id=task_id,
                    created_at=datetime.utcnow()
                )
                db.add(new_favorite)
                db.commit()
                migrated_count += 1
            except IntegrityError:
                db.rollback()
            except Exception:
                db.rollback()
    
    print(f"用户收藏迁移完成: 成功 {migrated_count} 个")
    return migrated_count


def rebuild_all_embeddings(db, force_reset: bool = True):
    """
    使用当前 embedding 模型重新生成所有题目的向量并写入 Chroma。
    Args:
        db: 数据库会话
        force_reset: 是否重置现有 Chroma 数据（默认清空后重建）
    """
    print("=" * 60)
    print("开始重建向量数据库（使用当前阿里云 embedding 模型）")
    print("=" * 60)

    client = get_chroma_client()
    if force_reset and hasattr(client, "reset"):
        print("重置 Chroma 持久化存储...")
        client.reset()
        # 重新获取集合
        _ = get_chroma_collection()

    teachings = db.query(Teaching).all()
    total = len(teachings)
    success = 0
    failed = 0

    for idx, teaching in enumerate(teachings, start=1):
        q_text = teaching.question or ""
        if not q_text.strip():
            print(f"跳过无题目文本的记录: {teaching.task_id}")
            failed += 1
            continue
        emb = get_question_embedding(q_text)
        if not emb:
            print(f"生成 embedding 失败: {teaching.task_id}")
            failed += 1
            continue
        metadata = {
            "title": teaching.title,
            "main_tag": teaching.main_tag,
            "sub_tags": teaching.sub_tags,
            "is_math_problem": teaching.is_math_problem,
        }
        ok = add_teaching_embedding(
            task_id=teaching.task_id,
            question=q_text,
            embedding=emb,
            metadata=metadata,
        )
        if ok:
            success += 1
        else:
            failed += 1
        if idx % 20 == 0 or idx == total:
            print(f"进度: {idx}/{total}, 成功 {success}, 失败 {failed}")

    print("=" * 60)
    print(f"重建完成：总计 {total}，成功 {success}，失败 {failed}")
    print("=" * 60)


def main():
    """主函数"""
    rebuild_flag = "--rebuild-embeddings" in sys.argv
    no_reset = "--no-reset" in sys.argv

    print("=" * 60)
    print("开始数据迁移")
    print("=" * 60)
    
    # 初始化数据库
    print("初始化数据库...")
    init_db()
    print("✓ 数据库初始化完成")
    
    db = SessionLocal()
    try:
        if rebuild_flag:
            rebuild_all_embeddings(db, force_reset=not no_reset)
        else:
            # 迁移用户
            migrate_users(db)
            
            # 迁移教学内容
            storage_dir = backend_dir.parent / "storage"
            migrate_teachings(db, storage_dir, force_update=True)
            
            # 迁移用户收藏
            users_file = backend_dir / "users" / "users.json"
            migrate_favorites(db, users_file)
            
            print("=" * 60)
            print("数据迁移完成！")
            print("=" * 60)
    except Exception as e:
        print(f"迁移过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()


if __name__ == "__main__":
    main()


