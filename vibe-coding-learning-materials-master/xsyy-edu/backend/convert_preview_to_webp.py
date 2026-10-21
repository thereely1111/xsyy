#!/usr/bin/env python3
"""
将 storage 目录下所有 preview.png 转换为 WebP 格式
等比例缩小至约 100KB，保留原 PNG 文件
"""

import os
from pathlib import Path
from PIL import Image
import io

# 目标文件大小（字节）
TARGET_SIZE = 100 * 1024  # 100KB
TOLERANCE = 10 * 1024  # 允许误差 ±10KB

def get_file_size(file_path):
    """获取文件大小"""
    return os.path.getsize(file_path)

def optimize_image_to_webp(input_path, output_path, target_size=TARGET_SIZE, tolerance=TOLERANCE):
    """
    将图片转换为 WebP 格式，调整质量使文件大小接近目标大小
    
    Args:
        input_path: 输入图片路径
        output_path: 输出 WebP 路径
        target_size: 目标文件大小（字节）
        tolerance: 允许的误差范围（字节）
    
    Returns:
        (success: bool, final_size: int, quality: int)
    """
    try:
        # 打开原图
        with Image.open(input_path) as img:
            # 转换为 RGB 模式（WebP 需要）
            if img.mode in ('RGBA', 'LA', 'P'):
                # 如果有透明通道，创建白色背景
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = rgb_img
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            
            original_size = img.size
            original_ratio = original_size[0] / original_size[1]
            
            # 初始质量值
            quality = 85
            min_quality = 30
            max_quality = 95
            
            # 初始缩放比例（如果原图很大，先缩小）
            scale = 1.0
            if max(original_size) > 2000:
                # 如果图片很大，先缩小到合理尺寸
                scale = 2000 / max(original_size)
                new_size = (int(original_size[0] * scale), int(original_size[1] * scale))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            
            best_quality = quality
            best_size = target_size * 2  # 初始值，确保能找到更小的
            
            # 二分查找最佳质量值
            low, high = min_quality, max_quality
            iterations = 0
            max_iterations = 20
            
            while low <= high and iterations < max_iterations:
                quality = (low + high) // 2
                
                # 保存为 WebP 到内存
                buffer = io.BytesIO()
                img.save(buffer, format='WebP', quality=quality, method=6)
                buffer_size = buffer.tell()
                
                if abs(buffer_size - target_size) < abs(best_size - target_size):
                    best_size = buffer_size
                    best_quality = quality
                
                if buffer_size < target_size - tolerance:
                    # 文件太小，提高质量
                    low = quality + 1
                elif buffer_size > target_size + tolerance:
                    # 文件太大，降低质量
                    high = quality - 1
                else:
                    # 在目标范围内，找到最佳值
                    break
                
                iterations += 1
            
            # 如果还是太大，进一步缩小尺寸
            if best_size > target_size + tolerance:
                # 计算需要缩小的比例
                size_ratio = (target_size / best_size) ** 0.5  # 平方根，因为面积是长×宽
                new_width = int(img.size[0] * size_ratio)
                new_height = int(img.size[1] * size_ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                
                # 重新优化质量
                low, high = min_quality, max_quality
                iterations = 0
                while low <= high and iterations < max_iterations:
                    quality = (low + high) // 2
                    buffer = io.BytesIO()
                    img.save(buffer, format='WebP', quality=quality, method=6)
                    buffer_size = buffer.tell()
                    
                    if abs(buffer_size - target_size) < abs(best_size - target_size):
                        best_size = buffer_size
                        best_quality = quality
                    
                    if buffer_size < target_size - tolerance:
                        low = quality + 1
                    elif buffer_size > target_size + tolerance:
                        high = quality - 1
                    else:
                        break
                    iterations += 1
            
            # 使用最佳质量保存
            img.save(output_path, format='WebP', quality=best_quality, method=6)
            final_size = get_file_size(output_path)
            
            return True, final_size, best_quality
            
    except Exception as e:
        print(f"   ✗ 处理失败: {e}")
        return False, 0, 0

def process_storage_directory(storage_dir):
    """处理 storage 目录下的所有 preview.png 文件"""
    storage_path = Path(storage_dir)
    
    if not storage_path.exists():
        print(f"错误: {storage_dir} 目录不存在")
        return
    
    # 查找所有 preview.png 文件
    preview_files = list(storage_path.rglob("preview.png"))
    
    if not preview_files:
        print("未找到任何 preview.png 文件")
        return
    
    print(f"找到 {len(preview_files)} 个 preview.png 文件")
    print("=" * 60)
    
    success_count = 0
    skip_count = 0
    error_count = 0
    total_original_size = 0
    total_webp_size = 0
    
    for i, png_path in enumerate(preview_files, 1):
        # 生成 WebP 文件路径
        webp_path = png_path.parent / "preview.webp"
        
        # 获取原图大小
        original_size = get_file_size(png_path)
        total_original_size += original_size
        
        print(f"[{i}/{len(preview_files)}] {png_path.parent.name}/preview.png")
        print(f"   原图大小: {original_size / 1024:.2f} KB")
        
        # 检查是否已存在 WebP 文件
        if webp_path.exists():
            webp_size = get_file_size(webp_path)
            if 90 * 1024 <= webp_size <= 110 * 1024:
                print(f"   ⏭ 已存在合适的 WebP 文件 ({webp_size / 1024:.2f} KB)，跳过")
                skip_count += 1
                total_webp_size += webp_size
                continue
        
        # 转换为 WebP
        success, final_size, quality = optimize_image_to_webp(png_path, webp_path)
        
        if success:
            total_webp_size += final_size
            reduction = (1 - final_size / original_size) * 100
            print(f"   ✓ 转换成功: {final_size / 1024:.2f} KB (质量: {quality}, 压缩率: {reduction:.1f}%)")
            success_count += 1
        else:
            error_count += 1
        
        print()
    
    # 输出统计信息
    print("=" * 60)
    print("处理完成！")
    print(f"  成功: {success_count} 个")
    print(f"  跳过: {skip_count} 个")
    print(f"  失败: {error_count} 个")
    print(f"  原图总大小: {total_original_size / 1024 / 1024:.2f} MB")
    print(f"  WebP 总大小: {total_webp_size / 1024 / 1024:.2f} MB")
    if total_original_size > 0:
        total_reduction = (1 - total_webp_size / total_original_size) * 100
        print(f"  总压缩率: {total_reduction:.1f}%")

if __name__ == "__main__":
    # 获取 storage 目录路径（相对于脚本位置）
    script_dir = Path(__file__).resolve().parent
    storage_dir = script_dir.parent / "storage"
    
    print("=" * 60)
    print("Preview.png 转 WebP 工具")
    print("=" * 60)
    print(f"Storage 目录: {storage_dir}")
    print()
    
    process_storage_directory(storage_dir)

