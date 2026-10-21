# 【函数域案例层】完整函数动画成品样例（few-shot 锚点）

> 本文件是 `domain_function` 的**案例层**，由 `router_config.json` 按 `question_type` 命中注入。
> 用途：给模型提供"一条**完整、平滑、铺满坐标系**的函数曲线到底长什么样"的成品参照，
> 直接纠正"画不完整 / 缩一角 / 锯齿 / 双曲线不对称"等失真。
> 三个样例覆盖了函数域最高频的三类：二次函数（利润最值）、反比例函数（双曲线）、一次函数（直线）。
> 坐标均用 `50_pattern_function_curve.md` 的映射配方实算，可直接模仿。

---

## 样例 1 · 二次函数利润最值（利润折扣问题）

**题目**：每件成本 10 元；单价 30 元时月售 500 件；单价每提高 2 元，月销量减 20 件。求最大月利润。
**解析式**：设提价 x 个 2 元，利润 `W = (20+2x)(500-20x) = -40x² + 600x + 10000`。
**范围**：x∈[0,25]（销量≥0），W∈[0,13000]；顶点 x=7.5，W=12250（单价 45 元）。

**映射配方**（x∈[0,25]→[70,750]，y∈[0,13000]→[518,205]，原点 O=(70,518)）：

| x | 0 | 2 | 4 | 6 | 7.5(顶点) | 9 | 12 | 15 | 18 | 21 | 23 | 25 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| W | 10000 | 11040 | 11760 | 12160 | **12250** | 12160 | 11440 | 10000 | 7840 | 4960 | 2640 | 0 |
| 像素(sx,sy) | (70,277) | (124,253) | (179,235) | (233,225) | **(274,223)** | (315,225) | (396,243) | (478,277) | (560,329) | (641,399) | (696,454) | (750,518) |

**关键 SVG 片段**（persistent 坐标系 + 临时生长曲线）：
```html
<!-- 坐标系 persistent -->
<g id="coord" class="svg-elem" x-show="sceneStep >= 1">
  <line id="xaxis" class="svg-elem" x1="70" y1="518" x2="750" y2="518" stroke="#2b2b2b" marker-end="url(#arrow)"/>
  <line id="yaxis" class="svg-elem" x1="70" y1="518" x2="70" y2="205" stroke="#2b2b2b" marker-end="url(#arrow)"/>
  <text id="olabel" class="svg-elem" x="58" y="534" fill="#2b2b2b">O</text>
</g>
<!-- 抛物线：pathLength 归一化 + 生长 -->
<path id="profitCurve" class="svg-elem" x-show="sceneStep >= 3"
      fill="none" stroke="#2f5fde" stroke-width="3"
      pathLength="1" style="stroke-dasharray:1; stroke-dashoffset:1"
      d="M70,277 L124,253 L179,235 L233,225 L274,223 L315,225 L396,243 L478,277 L560,329 L641,399 L696,454 L750,518"/>
<!-- 顶点聚焦 -->
<circle id="vertex" class="svg-elem" x-show="sceneStep >= 4" cx="274" cy="223" r="5" fill="#d6432f"/>
<line id="axisSym" class="svg-elem" x-show="sceneStep >= 4" x1="274" y1="223" x2="274" y2="518"
      stroke="#2b2b2b" stroke-width="1" stroke-dasharray="4 4"/>
<text id="vertexLabel" class="svg-elem" x-show="sceneStep >= 4" x="284" y="218" fill="#d6432f">顶点(7.5, 12250)</text>
```

**步骤拆解**：① 建系（坐标轴 persistent）② 标顶点与关键点（朱砂圆点）③ 曲线生长（dashoffset 1→0）④ 对称轴虚线 + 顶点标注 + 顶部解析式 / 底部"最大利润 12250 元"。

---

## 样例 2 · 反比例函数双曲线（中心反射对称）

**题目**：画 `y = 6/x` 的图象，并指出 k>0 时图象所在象限。
**要点**：原点 O 置绘图区几何中心；第一支取密集点，第二支对第一支做 **(x,y)→(-x,-y)** 中心反射。
**映射配方**：原点 O=(410,360)，比例 35 px/单位（x∈[-8,8]→[130,690]，y∈[-8,8]→[80,640] 区间内）。

| 第一支 x | 1 | 2 | 3 | 4 | 6 | 8 |
|---|---|---|---|---|---|---|
| y=6/x | 6 | 3 | 2 | 1.5 | 1 | 0.75 |
| 像素(正支) | (445,150) | (480,255) | (515,290) | (550,307) | (620,325) | (690,334) |

**第二支 = 第一支中心反射 (x,y)→(-x,-y) 关于 (410,360)**：
(375,570) (340,465) (305,430) (270,412) (200,395) (130,386)

**关键 SVG 片段**：
```html
<g id="coord" class="svg-elem" x-show="sceneStep >= 1">
  <line id="xaxis" class="svg-elem" x1="70" y1="360" x2="750" y2="360" stroke="#2b2b2b" marker-end="url(#arrow)"/>
  <line id="yaxis" class="svg-elem" x1="410" y1="518" x2="410" y2="205" stroke="#2b2b2b" marker-end="url(#arrow)"/>
  <text id="olabel" class="svg-elem" x="398" y="376" fill="#2b2b2b">O</text>
</g>
<path id="hyperbola" class="svg-elem" x-show="sceneStep >= 3" fill="none" stroke="#2f5fde" stroke-width="3"
      pathLength="1" style="stroke-dasharray:1; stroke-dashoffset:1"
      d="M445,150 L480,255 L515,290 L550,307 L620,325 L690,334
         M375,570 L340,465 L305,430 L270,412 L200,395 L130,386"/>
```
> 注意：两支必须是**同一 path 的两段**（或两段 path 用同一生成逻辑），禁止各自独立采样导致一长一短、一胖一瘦；曲线逼近坐标轴但不接触，禁止红色斜构造线。

---

## 样例 3 · 一次函数直线（简版）

**题目**：画 `y = 2x + 1`（x∈[-3,4]）。
**映射配方**：x∈[-3,4]→[70,750]，y∈[-5,9]→[518,205]，原点 O=(70,518)。
**三点**：(-3,-5)→(70,518)、(0,1)→(361,384)、(4,9)→(750,205)。
**曲线**：直线连接三点（非折线、非多段），`stroke="#2f5fde"`，生长同前（pathLength+stroke-dashoffset）。

---

## 自检要点（生成前对照）

- 坐标系铺满中部带、原点按数值范围定位（反比例必须置中心）；
- 曲线平滑完整、两端到坐标轴附近、无截断、无尖角；
- 所有采样点像素坐标用配方实算、全部落在 viewBox 内；
- 抛物线有顶点+对称轴、双曲线两支中心反射对称、交点 A/B 标注；
- 生长统一用 `pathLength`+`stroke-dashoffset`，颜色符合三色体系。
