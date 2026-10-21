import httpx
import json
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)


class AIService:
    def __init__(self):
        self.deepseek_api_key = settings.DEEPSEEK_API_KEY
        self.deepseek_base_url = settings.DEEPSEEK_BASE_URL
        self.deepseek_model = settings.DEEPSEEK_MODEL
        self.gemini_api_key = settings.GEMINI_API_KEY
        self.gemini_model = settings.GEMINI_MODEL

    async def analyze_problem(self, content: str) -> dict:
        if not self.deepseek_api_key:
            logger.info("DeepSeek API key not configured, using mock analysis")
            return self._mock_analysis(content)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.deepseek_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.deepseek_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.deepseek_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": """你是一位资深数学教师，负责分析数学题目。
请从题目中提取以下信息，返回JSON格式：
{
    "title": "简洁的题目标题",
    "primary_tag": "主标签（代数/几何/概率/数论/组合）",
    "secondary_tags": ["子标签1", "子标签2"],
    "difficulty": "easy/medium/hard/olympiad",
    "knowledge_points": [
        {"name": "知识点名称", "mastery": "了解/理解/掌握/应用"}
    ],
    "estimated_time": 预计完成时间（分钟）
}"""
                            },
                            {
                                "role": "user",
                                "content": content
                            }
                        ],
                        "temperature": 0.3,
                        "max_tokens": 500
                    }
                )
                result = response.json()
                content_text = result["choices"][0]["message"]["content"]
                return json.loads(content_text)

        except Exception as e:
            logger.error(f"DeepSeek API call failed: {e}")
            return self._mock_analysis(content)

    def _mock_analysis(self, content: str) -> dict:
        if "函数" in content or "方程" in content:
            primary_tag = "代数"
            secondary_tags = ["函数", "方程"]
        elif "三角形" in content or "几何" in content:
            primary_tag = "几何"
            secondary_tags = ["平面几何", "三角形"]
        elif "概率" in content or "统计" in content:
            primary_tag = "概率"
            secondary_tags = ["概率计算", "统计"]
        else:
            primary_tag = "数学"
            secondary_tags = ["基础"]

        return {
            "title": f"数学题目分析",
            "primary_tag": primary_tag,
            "secondary_tags": secondary_tags,
            "difficulty": "medium",
            "knowledge_points": [
                {"name": "数学基础", "mastery": "理解"}
            ],
            "estimated_time": 15
        }

    async def generate_teaching_steps(
        self,
        problem_content: str,
        analysis: dict
    ) -> dict:
        if not self.deepseek_api_key:
            logger.info("DeepSeek API key not configured, using mock teaching steps")
            return self._mock_teaching_steps(analysis)

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    f"{self.deepseek_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.deepseek_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.deepseek_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": """你是一位资深数学教师，负责为数学题目设计教学方案。

请根据以下题目和分析结果，设计一个结构化的教学方案，返回JSON格式：

{
    "knowledge_points": ["知识点1", "知识点2", "知识点3"],
    "steps": [
        {"title": "步骤1标题", "description": "详细解释", "interaction_hint": "可选提示"},
        {"title": "步骤2标题", "description": "详细解释", "interaction_hint": "可选提示"}
    ],
    "common_mistakes": ["错误1", "错误2"],
    "practice_suggestion": {
        "type": "slider|choice|input",
        "question": "练习题目",
        "options": ["选项1", "选项2"]
    }
}

注意：
- knowledge_points 列出3-5个核心知识点
- steps 包含2-4个解题步骤
- common_mistakes 列出2-3个常见错误
- practice_suggestion 中的type可以是：slider(滑块)、choice(选择题)、input(填空)
- 只返回JSON，不要有任何其他文字"""
                            },
                            {
                                "role": "user",
                                "content": f"题目：{problem_content}\n\n分析结果：{analysis}"
                            }
                        ],
                        "temperature": 0.5,
                        "max_tokens": 1500
                    }
                )
                result = response.json()
                content_text = result["choices"][0]["message"]["content"]
                return json.loads(content_text)

        except Exception as e:
            logger.error(f"DeepSeek teaching steps API call failed: {e}")
            return self._mock_teaching_steps(analysis)

    def _mock_teaching_steps(self, analysis: dict) -> dict:
        primary_tag = analysis.get("primary_tag", "数学")
        secondary_tags = analysis.get("secondary_tags", [])

        return {
            "knowledge_points": [f"{primary_tag}基础", "解题思路", "计算技巧"] + secondary_tags[:2],
            "steps": [
                {"title": "理解题意", "description": "仔细阅读题目，明确已知条件和求解目标", "interaction_hint": "尝试用自己的话复述题目"},
                {"title": "分析问题", "description": "识别题目类型，选择合适的解题方法", "interaction_hint": "回顾相关知识点"},
                {"title": "逐步求解", "description": "按照选定方法，逐步计算", "interaction_hint": "注意每一步的推导"},
                {"title": "检验结果", "description": "验证答案的正确性", "interaction_hint": "代入原题检验"}
            ],
            "common_mistakes": [
                "计算粗心导致错误",
                "未检验答案的合理性",
                "忽略题目中的隐含条件"
            ],
            "practice_suggestion": {
                "type": "choice",
                "question": "下列哪个选项正确？",
                "options": ["A", "B", "C", "D"]
            }
        }

    async def generate_application(
        self,
        analyze_result: dict,
        question_content: str,
        options: dict,
        teaching_steps: dict = None
    ) -> str:
        if not self.gemini_api_key:
            logger.info("Gemini API key not configured, using mock HTML generation")
            return self._generate_mock_html(analyze_result, question_content, options, teaching_steps)

        try:
            import google.generativeai as genai
            genai.configure(api_key=self.gemini_api_key)
            model = genai.GenerativeModel(self.gemini_model)

            teaching_steps_str = ""
            if teaching_steps:
                teaching_steps_str = f"""
教学步骤设计：
- 知识点：{', '.join(teaching_steps.get('knowledge_points', []))}
- 分步指导：
{chr(10).join([f"  {i+1}. {s['title']}: {s['description']}" for i, s in enumerate(teaching_steps.get('steps', []))])}
- 常见错误：{', '.join(teaching_steps.get('common_mistakes', []))}
- 练习建议：{teaching_steps.get('practice_suggestion', {}).get('question', '')}
"""

            prompt = f"""请为以下数学题目生成一个交互式HTML教学应用：

题目：{question_content}

分析结果：
- 标题：{analyze_result.get('title', '数学题目')}
- 主标签：{analyze_result.get('primary_tag', '数学')}
- 子标签：{', '.join(analyze_result.get('secondary_tags', []))}
- 难度：{analyze_result.get('difficulty', 'medium')}
{teaching_steps_str}

要求：
1. 使用内嵌Tailwind CSS（通过script标签引入cdn）
2. 新中式风格设计（墨蓝色#1a365d、米白背景#f7f3e9、强调色#a3d9ff）
3. **四区块布局结构**：
   - 标题区：顶部固定，包含标题、标签、难度
   - 画布区：桌面端与步骤区并排（占50%），移动端100%，至少400px高，浅米白背景，内阴影
   - 步骤区：桌面端与画布区并排，垂直卡片列表，带虚线分隔，当前步骤高亮
   - 控制区：底部跨列，包含练习控件和反馈提示
4. 每个区块使用独立的圆角白色卡片，带阴影，有彩色渐变标题栏
5. 步骤区支持点击某一步骤，高亮显示已完成的步骤
6. 响应式设计，移动端全列
7. 纯HTML单文件，无外部依赖（除了Tailwind CDN）

请直接输出HTML代码，不需要任何说明。"""

            response = model.generate_content(prompt)
            return response.text

        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            return self._generate_mock_html(analyze_result, question_content, options, teaching_steps)

    def _generate_mock_html(
        self,
        analyze_result: dict,
        question_content: str,
        options: dict,
        teaching_steps: dict = None
    ) -> str:
        title = analyze_result.get("title", "数学题目")
        primary_tag = analyze_result.get("primary_tag", "代数")
        secondary_tags = analyze_result.get("secondary_tags", [])
        difficulty = analyze_result.get("difficulty", "medium")

        if not teaching_steps:
            teaching_steps = self._mock_teaching_steps(analyze_result)

        steps = teaching_steps.get("steps", [])
        knowledge_points = teaching_steps.get("knowledge_points", [])
        common_mistakes = teaching_steps.get("common_mistakes", [])
        practice = teaching_steps.get("practice_suggestion", {})

        difficulty_labels = {
            "easy": "简单",
            "medium": "中等",
            "hard": "困难",
            "olympiad": "竞赛级"
        }

        difficulty_label = difficulty_labels.get(difficulty, "中等")

        # 生成知识点 HTML
        knowledge_html = "".join([f'<span class="inline-block bg-xsyy-blue/10 text-xsyy-blue px-4 py-2 rounded-full text-sm mr-2 mb-2 font-medium">{kp}</span>' for kp in knowledge_points[:5]])

        # 生成常见错误 HTML
        mistakes_html = "".join([f'<li class="text-red-700 pl-2 border-l-3 border-red-500 py-2">⚠️ {m}</li>' for m in common_mistakes[:3]])

        # 生成步骤区 HTML
        steps_html = ""
        for i, step in enumerate(steps[:4]):
            is_active = "border-xsyy-blue" if i == 0 else "border-gray-300 opacity-70"
            step_number_circle = "bg-xsyy-blue" if i == 0 else "bg-gray-400"
            title_color = "text-xsyy-blue" if i == 0 else "text-gray-700"
            hint_html = f"<div class='mt-3 bg-blue-50 border-l-3 border-blue-500 p-3 rounded-r-lg'><p class='text-blue-800 text-sm'>💡 {step.get('interaction_hint', '')}</p></div>" if step.get('interaction_hint') else ""
            steps_html += f'''
            <div class="step-item p-6 cursor-pointer hover:bg-xsyy-cream/50 transition border-l-4 {is_active}" data-step="{i+1}" onclick="selectStep({i+1})">
                <div class="flex items-start gap-4">
                    <div class="flex-shrink-0 w-10 h-10 {step_number_circle} text-white rounded-full flex items-center justify-center font-bold text-lg">{i+1}</div>
                    <div class="flex-1">
                        <h3 class="font-bold {title_color} text-lg mb-2">{step.get('title', '')}</h3>
                        <p class="text-gray-700 leading-relaxed">{step.get('description', '')}</p>
                        {hint_html}
                    </div>
                </div>
            </div>'''

        # 生成练习区 HTML
        practice_type = practice.get("type", "choice")
        practice_question = practice.get("question", "尝试回答以下问题")
        practice_options = practice.get("options", [])

        if practice_type == "slider":
            practice_html = f'''
            <div class="bg-xsyy-cream rounded-xl p-5">
                <p class="font-bold text-xsyy-blue mb-4">{practice_question}</p>
                <input type="range" min="0" max="100" value="50" class="w-full h-2 bg-gray-300 rounded-lg appearance-none cursor-pointer" id="slider-input" oninput="document.getElementById('slider-value').textContent=this.value; onControlChange()">
                <div class="flex justify-between items-center mt-3">
                    <span class="text-gray-500">0</span>
                    <span id="slider-value" class="text-2xl font-bold text-xsyy-blue">50</span>
                    <span class="text-gray-500">100</span>
                </div>
            </div>'''
        elif practice_type == "input":
            practice_html = f'''
            <div class="bg-xsyy-cream rounded-xl p-5">
                <p class="font-bold text-xsyy-blue mb-4">{practice_question}</p>
                <input type="text" id="answer-input" class="w-full px-4 py-3 border-2 border-gray-300 rounded-lg focus:border-xsyy-blue focus:outline-none focus:ring-2 focus:ring-xsyy-blue/20 transition text-lg" placeholder="请输入答案...">
            </div>'''
        else:
            options_html = "".join([f'''
                <label class="flex items-center p-4 bg-white rounded-lg hover:bg-gray-50 cursor-pointer transition border-2 border-transparent hover:border-xsyy-blue/30">
                    <input type="radio" name="practice-answer" value="{chr(65+i)}" class="mr-4 w-5 h-5 text-xsyy-blue focus:ring-xsyy-blue" onchange="onControlChange()">
                    <span class="text-lg text-gray-800">{chr(65+i)}. {opt}</span>
                </label>''' for i, opt in enumerate(practice_options[:4])])
            practice_html = f'''
            <div class="bg-xsyy-cream rounded-xl p-5">
                <p class="font-bold text-xsyy-blue mb-4">{practice_question}</p>
                <div class="space-y-3">
                    {options_html}
                </div>
            </div>'''

        # 生成完整 HTML
        html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - 象数演易</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {{
            theme: {{
                extend: {{
                    colors: {{
                        'xsyy-blue': '#1a365d',
                        'xsyy-cream': '#f7f3e9',
                        'xsyy-gold': '#d4a574',
                        'xsyy-cyan': '#a3d9ff'
                    }}
                }}
            }}
        }}
    </script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;700&display=swap');
        body {{ font-family: 'Noto Serif SC', serif; }}
        .paper-texture {{ background-image: url("data:image/svg+xml,%3Csvg width='100' height='100' viewBox='0 0 100 100' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.8' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.03'/%3E%3C/svg%3E"); }}
    </style>
</head>
<body class="min-h-screen bg-xsyy-cream paper-texture">
    <!-- 区块1: 标题区 -->
    <header class="bg-gradient-to-r from-xsyy-blue to-blue-800 text-white py-6 shadow-xl sticky top-0 z-50">
        <div class="container mx-auto px-4">
            <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-4">
                <div class="flex-1">
                    <h1 class="text-2xl md:text-3xl font-bold mb-3">{title}</h1>
                    <div class="flex flex-wrap items-center gap-3">
                        <span class="px-3 py-1 bg-xsyy-cyan/20 text-xsyy-cyan rounded-full text-sm font-medium">{primary_tag}</span>
                        {''.join([f'<span class="px-3 py-1 bg-white/10 rounded-full text-sm">{t}</span>' for t in secondary_tags[:2]])}
                        <span class="px-3 py-1 bg-green-500/20 text-green-300 rounded-full text-sm font-medium">{difficulty_label}</span>
                    </div>
                </div>
            </div>
        </div>
    </header>

    <main class="container mx-auto px-4 py-8 max-w-7xl">
        <!-- 桌面端布局: 画布区 + 步骤区并排 -->
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-8 mb-8">
            <!-- 区块2: 画布区 -->
            <section class="bg-white rounded-2xl shadow-xl overflow-hidden">
                <div class="bg-gradient-to-r from-xsyy-blue to-blue-700 text-white px-6 py-4">
                    <h2 class="text-lg font-bold flex items-center gap-2">
                        <span class="text-2xl">🎨</span> 动态演示
                    </h2>
                </div>
                <div id="canvas-area" class="p-6 bg-gradient-to-br from-xsyy-cream to-white min-h-[400px] flex items-center justify-center">
                    <div class="text-center">
                        <div class="text-7xl mb-4 animate-bounce">📐</div>
                        <p class="text-gray-600 text-lg">数学可视化演示</p>
                    </div>
                </div>
            </section>

            <!-- 区块3: 步骤区 -->
            <section class="bg-white rounded-2xl shadow-xl overflow-hidden">
                <div class="bg-gradient-to-r from-xsyy-blue to-blue-700 text-white px-6 py-4 flex items-center justify-between">
                    <h2 class="text-lg font-bold flex items-center gap-2">
                        <span class="text-2xl">📝</span> 解题步骤
                    </h2>
                    <button onclick="toggleAllSteps()" class="px-4 py-2 bg-white/20 rounded-lg hover:bg-white/30 transition text-sm font-medium">
                        <span id="toggle-btn-text">收起全部</span>
                    </button>
                </div>
                <div id="steps-container" class="divide-y divide-dashed divide-gray-300">
                    {steps_html}
                </div>
            </section>
        </div>

        <!-- 区块4: 控制区 (跨列底部) -->
        <section class="bg-white rounded-2xl shadow-xl overflow-hidden mb-8">
            <div class="bg-gradient-to-r from-xsyy-gold to-yellow-600 text-white px-6 py-4">
                <h2 class="text-lg font-bold flex items-center gap-2">
                    <span class="text-2xl">🎮</span> 互动练习
                </h2>
            </div>
            <div class="p-6">
                {practice_html}

                <div id="feedback-area" class="mt-6 p-4 bg-green-50 border-l-4 border-green-500 rounded-r-lg hidden">
                    <p class="text-green-800 font-medium" id="feedback-text"></p>
                </div>

                <div class="mt-6 flex flex-wrap gap-3">
                    <button onclick="submitAnswer()" class="px-6 py-3 bg-xsyy-blue text-white rounded-xl hover:bg-blue-800 transition font-medium shadow-md">
                        ✅ 提交答案
                    </button>
                    <button onclick="showHint()" class="px-6 py-3 bg-gray-500 text-white rounded-xl hover:bg-gray-600 transition font-medium shadow-md">
                        💡 提示
                    </button>
                    <button onclick="resetAll()" class="px-6 py-3 bg-gray-300 text-gray-700 rounded-xl hover:bg-gray-400 transition font-medium shadow-md">
                        🔄 重置
                    </button>
                </div>
            </div>
        </section>

        <!-- 题目描述区 -->
        <section class="bg-white rounded-2xl shadow-xl overflow-hidden mb-8">
            <div class="bg-gradient-to-r from-gray-700 to-gray-800 text-white px-6 py-4">
                <h2 class="text-lg font-bold flex items-center gap-2">
                    <span class="text-2xl">📖</span> 题目内容
                </h2>
            </div>
            <div class="p-6">
                <div class="bg-xsyy-cream rounded-xl p-6">
                    <p class="text-lg text-gray-800 leading-relaxed">{question_content}</p>
                </div>
            </div>
        </section>

        <!-- 知识点区 -->
        <section class="bg-white rounded-2xl shadow-xl overflow-hidden mb-8">
            <div class="bg-gradient-to-r from-purple-600 to-purple-700 text-white px-6 py-4">
                <h2 class="text-lg font-bold flex items-center gap-2">
                    <span class="text-2xl">📚</span> 核心知识点
                </h2>
            </div>
            <div class="p-6">
                <div class="flex flex-wrap gap-3">
                    {knowledge_html}
                </div>
            </div>
        </section>

        <!-- 常见错误区 -->
        <section class="bg-white rounded-2xl shadow-xl overflow-hidden">
            <div class="bg-gradient-to-r from-red-600 to-red-700 text-white px-6 py-4">
                <h2 class="text-lg font-bold flex items-center gap-2">
                    <span class="text-2xl">⚠️</span> 常见错误
                </h2>
            </div>
            <div class="p-6">
                <ul class="space-y-3">
                    {mistakes_html}
                </ul>
            </div>
        </section>
    </main>

    <footer class="bg-xsyy-blue text-white py-6 mt-12">
        <div class="container mx-auto px-4 text-center">
            <p class="text-gray-300">&copy; 2026 象数演易 (XSYY) - AI驱动的数学教学平台</p>
        </div>
    </footer>

    <script>
        let currentStep = 1;
        let allExpanded = true;

        function selectStep(stepNum) {{
            currentStep = stepNum;
            document.querySelectorAll('.step-item').forEach((element, index) => {{
                const i = index + 1;
                const circle = element.querySelector('.flex-shrink-0');
                const title = element.querySelector('h3');

                if (i <= stepNum) {{
                    element.classList.remove('border-gray-300', 'opacity-70');
                    element.classList.add('border-xsyy-blue');
                    circle.classList.remove('bg-gray-400');
                    circle.classList.add('bg-xsyy-blue');
                    title.classList.remove('text-gray-700');
                    title.classList.add('text-xsyy-blue');
                }} else {{
                    element.classList.add('border-gray-300', 'opacity-70');
                    element.classList.remove('border-xsyy-blue');
                    circle.classList.add('bg-gray-400');
                    circle.classList.remove('bg-xsyy-blue');
                    title.classList.add('text-gray-700');
                    title.classList.remove('text-xsyy-blue');
                }}
            }});
            showFeedback(`正在学习第 ${{stepNum}} 步...`, 'info');
        }}

        function toggleAllSteps() {{
            allExpanded = !allExpanded;
            document.getElementById('toggle-btn-text').textContent = allExpanded ? '收起全部' : '展开全部';
        }}

        function submitAnswer() {{
            showFeedback('答案已提交！', 'success');
        }}

        function showHint() {{
            const hints = ['仔细分析已知条件', '回顾相关公式', '画图辅助理解', '检查计算过程'];
            const randomHint = hints[Math.floor(Math.random() * hints.length)];
            showFeedback(randomHint, 'info');
        }}

        function resetAll() {{
            selectStep(1);
            const slider = document.getElementById('slider-input');
            if (slider) slider.value = 50;
            const valueDisplay = document.getElementById('slider-value');
            if (valueDisplay) valueDisplay.textContent = '50';
            const textInput = document.getElementById('answer-input');
            if (textInput) textInput.value = '';
            const radioInputs = document.querySelectorAll('input[name="practice-answer"]');
            radioInputs.forEach(r => r.checked = false);
            showFeedback('已重置', 'info');
        }}

        function onControlChange() {{
            // 可以在这里添加互动逻辑
        }}

        function showFeedback(text, type = 'info') {{
            const area = document.getElementById('feedback-area');
            const textEl = document.getElementById('feedback-text');
            textEl.textContent = text;
            area.classList.remove('hidden', 'bg-green-50', 'bg-blue-50', 'border-green-500', 'border-blue-500');
            
            if (type === 'success') {{
                area.classList.add('bg-green-50', 'border-green-500');
            }} else {{
                area.classList.add('bg-blue-50', 'border-blue-500');
            }}
            
            area.classList.remove('hidden');
            setTimeout(() => {{
                area.classList.add('hidden');
            }}, 4000);
        }}

        document.addEventListener('DOMContentLoaded', () => {{
            console.log('象数演易 - 四区块教学应用加载完成');
        }});
    </script>
</body>
</html>'''
        return html

    async def check_if_math(self, content: str) -> dict:
        if not self.deepseek_api_key:
            logger.info("DeepSeek API key not configured, using fallback validation")
            return self._fallback_validation(content)

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self.deepseek_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.deepseek_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.deepseek_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": """你是一个数学题目判定专家。请判断以下内容是否为数学题，并判断题目描述中是否包含独立的几何图形、函数图像或图表（如三角形、圆、抛物线、柱状图等）。

请只返回JSON格式，不要有其他文字：
{"is_math": true/false, "confidence": 0.0-1.0, "has_graph": true/false, "reason": "简短原因说明"}"""
                            },
                            {
                                "role": "user",
                                "content": f"请判断以下内容：{content}"
                            }
                        ],
                        "temperature": 0.1,
                        "max_tokens": 200
                    }
                )
                result = response.json()
                content_text = result["choices"][0]["message"]["content"]
                return json.loads(content_text)

        except Exception as e:
            logger.error(f"DeepSeek validation API call failed: {e}")
            return self._fallback_validation(content)

    async def check_if_math_from_image(self, image_base64: str) -> dict:
        if not self.deepseek_api_key:
            logger.info("DeepSeek API key not configured, using fallback validation")
            return self._fallback_validation("")

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    f"{self.deepseek_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.deepseek_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.deepseek_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": """你是一个数学题目判定专家。请分析这张图片是否为数学题目的截图，并判断其中是否包含独立的几何图形、函数图像或图表（如三角形、圆、抛物线、柱状图等）。

请只返回JSON格式，不要有其他文字：
{"is_math": true/false, "confidence": 0.0-1.0, "has_graph": true/false, "reason": "简短原因说明"}"""
                            },
                            {
                                "role": "user",
                                "content": f"[图片内容：{image_base64[:100]}...]"
                            }
                        ],
                        "temperature": 0.1,
                        "max_tokens": 200
                    }
                )
                result = response.json()
                content_text = result["choices"][0]["message"]["content"]
                return json.loads(content_text)

        except Exception as e:
            logger.error(f"DeepSeek image validation API call failed: {e}")
            return self._fallback_validation("")

    def _fallback_validation(self, content: str) -> dict:
        math_keywords = [
            "+", "-", "×", "÷", "=", "≠", ">", "<", "≥", "≤",
            "方程", "函数", "几何", "三角形", "四边形", "圆", "椭圆",
            "抛物线", "双曲线", "坐标", "向量", "数列", "级数",
            "概率", "统计", "平均数", "方差", "标准差",
            "微积分", "导数", "积分", "极限",
            "代数", "多项式", "因式分解", "配方",
            "角", "边", "面积", "体积", "周长",
            "sin", "cos", "tan", "cot", "sec", "csc",
            "log", "ln", "exp", "sqrt", "根号",
            "平行", "垂直", "对称", "旋转", "平移",
            "证明", "求解", "计算", "化简"
        ]

        content_lower = content.lower()
        matched_keywords = sum(1 for kw in math_keywords if kw.lower() in content_lower)

        is_math = matched_keywords >= 2
        confidence = min(0.3 + matched_keywords * 0.1, 0.95) if is_math else max(0.5 - matched_keywords * 0.1, 0.1)

        graph_keywords = ["图", "形", "象", "曲线", "图像", "坐标", "轴", "表"]
        has_graph = any(kw in content for kw in graph_keywords)

        return {
            "is_math": is_math,
            "confidence": confidence,
            "has_graph": has_graph,
            "reason": "基于关键词匹配判定" if is_math else "未检测到足够数学特征"
        }

    async def extract_core_question(self, content: str) -> str:
        if not self.deepseek_api_key:
            logger.info("DeepSeek API key not configured, using raw content")
            return self._fallback_extract(content)

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    f"{self.deepseek_base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.deepseek_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": self.deepseek_model,
                        "messages": [
                            {
                                "role": "system",
                                "content": """你是一个数学题干清洗专家。请从以下文本中提取核心题目内容，去掉：
1. 题号（如"1."、"(1)"、"【第1题】"等）
2. 废话引导语（如"请解答下列问题"、"思考一下"、"试着做一做"等）
3. 不必要的说明和描述
4. 冗余的空格、换行

只返回清洗后的题目文本，不要有任何解释或说明。如果内容已经是纯净题目，直接返回原内容。"""
                            },
                            {
                                "role": "user",
                                "content": f"请清洗以下题目内容：\n\n{content}"
                            }
                        ],
                        "temperature": 0.1,
                        "max_tokens": 1000
                    }
                )
                result = response.json()
                content_text = result["choices"][0]["message"]["content"].strip()
                return content_text

        except Exception as e:
            logger.error(f"DeepSeek extraction API call failed: {e}")
            return self._fallback_extract(content)

    def _fallback_extract(self, content: str) -> str:
        import re
        cleaned = re.sub(r'^[\d一二三四五六七八九十]+[.、)）]\s*', '', content)
        cleaned = re.sub(r'[\(（]?\d[\)）]?\s*', '', cleaned)
        noise_phrases = [
            '请解答下列问题', '请计算', '请回答', '思考一下', '试着做一做',
            '试一试', '动脑筋想一想', '大家来想一想', '下面是',
            '已知', '求', '证明'
        ]
        for phrase in noise_phrases:
            if phrase in cleaned and len(cleaned) < 100:
                pass
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned if len(cleaned) >= 5 else content


ai_service = AIService()
