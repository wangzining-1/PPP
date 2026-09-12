# 预算矢量化

适用于默认的位图→原生 PPT 重建。先完成全图理解和真实文字提取，输入去字后的 `graphics.png`。全局最多 1000 个图形叶子（path/shape），文字另计；`p:grpSp` 只是容器。必须另报复合路径的子路径数和节点数，不能用组合掩盖复杂度。

## 语义配置与背景

为每个可独立编辑的实体、线条或细胞器建立单位和灰度 PNG mask；灰度大于 127 的像素为归属。所有 mask 与原图同尺寸、互斥，路径相对于配置目录。先目视审查单位是否完整、邻接对象是否误合并、箭头是否被切断；颜色聚类或连通域本身不等于语义识别。

`semantic.json`：

```json
{
  "width": 700,
  "height": 678,
  "supersample": 3,
  "background_tolerance": 18,
  "background_model": "background-model.png",
  "units": [
    {"id": "cell-01", "mask": "masks/cell-01.png", "colors": 6, "protected": false},
    {"id": "arrow-01", "mask": "masks/arrow-01.png", "colors": 3, "protected": true}
  ]
}
```

- `background_seeds` 可选，默认四角；主体占据角点时先核对并选择真实背景种子，不能把主体作为背景入口。
- `background_tolerance` 默认 18。`background_model` 可选，为同尺寸 RGB PNG 颜色模型，路径相对配置目录；省略时按四角颜色做双线性插值。渐变应使用适合图像的颜色模型，不能只用局部相邻像素差不断扩散而吞掉主体。
- 背景候选由四角向内洪水填充取得，主体 mask 提供保护边界。审查 `background-mask.png` 后再接受结果。背景完全跳过，不生成矩形或大量渐变色带；保留对象内部的白色、浅色轮廓和高光。与主体粘连的辉光/投影归属相应单位，独立背景阴影不描摹。
- `colors` 是该单位起始调色板大小；`protected` 用于保护不可牺牲的单元，不能靠删除该单元或其关键关系满足预算。未分配的前景是待修复项，不能默认为背景。

## 构建与四级合并

使用配置中的本地 Python，先检查工具帮助。构建接口：

```text
scripts/run.ps1 budget plan <graphics.png> <semantic.json> --max-shapes 1000
# 用户确认计划后：
scripts/run.ps1 budget build <graphics.png> <semantic.json> <out-dir> --max-shapes 1000 --confirm-plan <plan标识>
```

输出 `graphics.svg`、`budget.json`、`groups.json`、`background-mask.png`、`foreground-mask.png`。工具不具备凭颜色自动理解任意机制图的保证；语义 mask 和质量检查仍由代理核对。

按以下顺序执行并记录实际使用的级别，达到预算后停止降级：

1. 合并相邻色块：ΔE < 15，或 RGB 每通道差均 < 20。使用哪种度量须记录，不能把不同 ΔE 公式的阈值混称同一测试。
2. 合并同一单位的近色层，采用原生渐变或主色块；只有导出器支持并已验证的渐变才能标为已实现。
3. 将包围盒宽、高均小于 4 像素的细块并入周围主导色；保留有机制意义的小箭头、离子或标记。
4. 按面积从小到大吸收剩余碎块。先组内、后组间；组间处理不得吞并独立语义对象。大面积主体的范围和主色保持，不能删除主体或整组达标。

若不能同时保住主体/机制并满足预算，输出失败项和候选计数。不能静默增加上限、返回位图、隐藏旧图，或只报告组数。SVG 中复合路径用于同色轮廓时仍须保留语义归属并披露全部子路径/节点数。

## 导出原生 PPT

```text
scripts/run.ps1 budget pptx <base-pptx文本模板> <out-dir> <new-pptx>
```

模板须为同尺寸、单页、无媒体的原生 PPTX；仅从顶层复制经过核对的真实文本框，不能使用带文字的旧图形或嵌套文本组。替换旧图形，不能复制旧图或旧背景。按 `groups.json` 输出真正的 `p:grpSp`，组内为原生 `p:sp`/几何路径，文本保持可修改内容。SVG 图片、EMF 图片、截图以及仅有名称的伪分组均不满足要求。工具接口不存在或执行失败时，应修复或报告阻塞，不伪称构建成功。

## 双重验收

预算和视觉分别判定，只有全部通过才称达标：

| 项目 | 检查 |
|---|---|
| 预算 | 从最终 PPTX 递归计数图形叶子 ≤1000；另报文本、组、子路径、节点数和文件体积 |
| 原生编辑 | 无嵌入图代替主体；语义单位对应原生组，文本内容、上下标、斜体正确 |
| 背景 | 背景没有图形；mask 没有吞掉浅色主体、边缘、高光或连通阴影 |
| 机制 | 所有单位、箭头方向/端点、抑制标志和标签逐项核对，无消失或误连接 |
| 保真 | 重读保存的 PPT 渲染；检查全图与最差局部，并分别报告前景误差与有意移除背景的差异 |

记录实际删减细节、渐变近似和剩余差异；不能由一个低平均像素误差推断机制正确。未实际运行的检查标“未运行”，未通过的项标“未通过”；结构验证不能替代 PowerPoint 桌面实机编辑测试。

构建目前使用 CIELAB 聚类与 RGB 各通道差 <20 的相邻色合并，预算压缩使用主色块，不声称已实现原生渐变拟合。半透明像素明确拒绝，须使用另经验证的原生透明度路径；完全透明像素直接跳过。protected 单元不参与预算强制调色板降级或碎块吸收。

执行 `scripts/run.ps1 budget audit final.pptx` 独立复算最终图形/文本/组/子路径/节点。finalize 入口先运行该门禁；审查 budget.json 的 unassigned_pixels 并修复遗漏之后，才可记录语义验收通过。结构审计不能独立判断某块是否语义背景。


保存后执行 `scripts/run.ps1 render candidate.pptx preview.png` 重读渲染，输出路径必须是新文件。`foreground-mask.png` 是前景误差统计范围；同时单独查看未归属区域，不能通过缩小 mask 隐藏漏画。轮廓以2–4倍边缘场分析和0.5px拟合产生直线/贝塞尔，禁止原始像素逐格追边。使用1px同色轮廓补偿接缝，最外缘最多偏移0.5px；必须在400%渲染中检查。


V3 groups.json 使用 definitions、组级 paints/default_paint 及 items[{ref,at,paint?}]；定义仅含M/L/C/Z命令。位置和控制点均吸附0.5px，引用展开后仍复算预算。budget.json 的 staircase_candidates 是几何候选数；edge_400_percent 默认为待验收，绝不能由候选为0自动标合格。
