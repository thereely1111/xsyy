# PyTorch DLL 加载失败问题修复指南

## 问题描述
错误信息：`OSError: [WinError 1114] 动态链接库(DLL)初始化例程失败。 Error loading "c10.dll" or one of its dependencies.`

## 原因分析
1. PyTorch 版本与系统不兼容
2. 缺少 Visual C++ Redistributable 运行时库
3. PyTorch 安装损坏或不完整

## 解决方案

### 方案 1：重新安装 PyTorch CPU 版本（推荐）

在虚拟环境中执行：

```powershell
# 激活虚拟环境
..\.venv\Scripts\activate

# 卸载现有的 torch
pip uninstall torch torchvision torchaudio -y

# 安装 CPU 版本的 PyTorch（更稳定，无需 CUDA）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
```

### 方案 2：安装 Visual C++ Redistributable

如果方案 1 无效，可能是缺少系统依赖：

1. 下载并安装 Microsoft Visual C++ Redistributable：
   - 下载地址：https://aka.ms/vs/17/release/vc_redist.x64.exe
   - 安装后重启计算机

2. 然后重新安装 PyTorch（参考方案 1）

### 方案 3：使用 conda 安装（如果使用 Anaconda）

```powershell
conda install pytorch torchvision torchaudio cpuonly -c pytorch
```

## 验证安装

安装完成后，运行测试脚本：

```powershell
python utils/embedding_utils.py
```

如果看到测试通过，说明 PyTorch 已正确安装。

## 注意事项

1. **延迟导入已实现**：`app.py` 中已将 `embedding_utils` 改为延迟导入，即使 PyTorch 有问题，应用也可以正常启动，只是相似度推荐功能不可用。

2. **首次使用**：首次运行 `embedding_utils.py` 时会自动下载模型（约 420MB），需要网络连接。

3. **性能**：CPU 版本的 PyTorch 速度较慢，但对于相似度计算已经足够。

## 如果问题仍然存在

1. 检查 Python 版本（建议 3.8-3.11）
2. 检查虚拟环境是否正确激活
3. 尝试创建新的虚拟环境并重新安装所有依赖
4. 检查系统是否有杀毒软件阻止 DLL 加载

