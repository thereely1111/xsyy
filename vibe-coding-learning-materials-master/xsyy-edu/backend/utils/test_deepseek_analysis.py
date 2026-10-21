"""
简单的测试脚本：使用与 pipeline 相同的 DeepSeek 分析方案测试题目分析效果
"""
import asyncio
import json
import sys
import io
from pathlib import Path

# 设置标准输出编码为 UTF-8（Windows 兼容）
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 添加 backend 目录到路径（因为现在在 utils 子目录中）
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

from classify_storage_tasks import (
    get_llm_classifier,
    analyze_question,
    parse_analysis_result
)


async def test_analysis(question: str):
    """测试单个题目的分析"""
    print("=" * 60)
    print(f"测试题目: {question}")
    print("=" * 60)
    
    try:
        # 1. 获取 LLM 分类器
        print("\n[1/3] 初始化 DeepSeek 分类器...")
        llm = get_llm_classifier()
        print("✓ 分类器初始化成功")
        
        # 2. 调用分析函数
        print("\n[2/3] 调用 DeepSeek API 分析题目...")
        result = await analyze_question(question, llm, max_validation_retries=3)
        
        if not result:
            print("❌ 分析失败，返回 None")
            return
        
        # 3. 输出结果
        print("\n[3/3] 分析结果:")
        print("-" * 60)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("-" * 60)
        
        # 4. 详细输出
        print("\n详细解析:")
        print(f"  是否为数学题: {result.get('is_math_problem', False)}")
        if result.get('is_math_problem'):
            print(f"  提取的题目: {result.get('question', 'N/A')}")
            print(f"  标题: {result.get('title', 'N/A')}")
            print(f"  判定理由: {result.get('reasoning', 'N/A')}")
            print(f"  主标签: {result.get('main_tag', 'N/A')}")
            print(f"  副标签: {result.get('sub_tags', [])}")
        else:
            print("  (非数学题，无分类信息)")
        
        print("\n" + "=" * 60)
        return result
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    """主函数：可以测试多个题目"""
    print("\n" + "=" * 60)
    print("DeepSeek 题目分析测试工具")
    print("=" * 60 + "\n")
    
    # 测试题目列表
    test_questions = [
        "小明有 12 个苹果，他想平均分给 3 个朋友，每个朋友能分到几个苹果？",
        "一个长方形的长是 8 厘米，宽是 5 厘米，求这个长方形的周长和面积。",
        "学校进行乒乓球选拔赛，每个参赛选手都要和其他所有选手各赛一场，一共有 10 位参赛选手，问一共要进行多少场比赛？",
    ]
    
    # 如果命令行有参数，使用命令行参数作为题目
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        await test_analysis(question)
    else:
        # 否则测试所有预设题目
        print(f"将测试 {len(test_questions)} 个题目\n")
        
        for i, question in enumerate(test_questions, 1):
            print(f"\n{'=' * 60}")
            print(f"测试 {i}/{len(test_questions)}")
            print(f"{'=' * 60}\n")
            await test_analysis(question)
            
            # 如果不是最后一个，等待一下
            if i < len(test_questions):
                print("\n等待 2 秒后继续下一个测试...\n")
                await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())

