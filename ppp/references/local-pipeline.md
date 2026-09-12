# 本地多阶段流水线

## 部署

`scripts/setup.ps1` 在独立虚拟环境安装 `requirements.lock`，将技能复制到 Codex 个人技能目录并生成 `runtime.local.json`。不修改捆绑 Python/Node。导出使用宿主 `@oai/artifact-tool` 与 `jszip`。不包含独立本地语言模型或 Office 许可证。运行 `scripts/run.ps1 doctor` 检查依赖、OCR模型初始化及Node导出模块。

安装参数 `-PythonExecutable`、`-NodeExecutable`、`-NodeModules` 使用工作区依赖工具返回的真实路径。配置失效时重新安装。OCR模型随 rapidocr-onnxruntime 包落地；转换不需要第三方矢量API，机制理解由当前 Codex 视觉模型完成。

## 默认预算流程

先阅读 [预算矢量化](budget-vectorization.md)，建立并审查语义 mask。先运行 `budget plan graphics.png semantic.json` 输出一行计划并等待确认，再运行 `budget build graphics.png semantic.json work/budget --confirm-plan <plan>`，用 `budget pptx text-template.pptx work/budget candidate.pptx` 输出原生分组，再用 `budget audit candidate.pptx` 递归检查 1000 图形硬上限。以下 trace/scene 命令用于局部几何或真实文字模板；不能整图描摹后绕过预算交付。

## 命令

以下均为 `scripts/run.ps1` 后的参数。路径替换为实际绝对路径，输出使用新文件/目录：

| 阶段 | 参数 | 产物/检查 |
| --- | --- | --- |
| 标准化与OCR | `prepare input.png work/prepared` | normalized.png、labels.json、manifest.json；核对全图与文字 |
| 去字候选 | `erase normalized.png labels.reviewed.json work/erased` | graphics.png、text-mask.png；检查箭头、边框是否受损 |
| 局部参考描摹（非默认交付） | `trace graphics.png work/traced` | graphics.svg、graphics.scene.json |
| 已有SVG导入 | `svg source.svg scene.json` | 严格子集转换；不支持项失败 |
| 文字回填 | `merge graphics.scene.json labels.reviewed.json scene.v1.json` | 图形路径+真实文本元素 |
| 导出与重读渲染 | `export scene.v1.json candidate.v1.pptx master.v1.svg --render render.v1.png` | 原生PPT、含文字Master SVG、从保存后PPTX重读的PNG |
| 最终封装验证 | `finalize work candidate.v1.pptx output/final.pptx` | 用明确工作区根目录和绝对文件路径，调用宿主finalizer，保留私有验证记录 |
| 原生对象核查 | `audit candidate.v1.pptx --scene scene.v1.json` | ID、原生类型、精确文字、无位图和外部关系 |
| 视觉核查 | `compare normalized.png render.v1.png work/qa-v1` | 误差、叠加、差异、最差局部 |

简单图形直接编写少量原生形状的场景即可；复杂主体先描摹，再将重复规则轮廓替换为简洁形状。描摹自然纹理、渐变和抗锯齿可能产生很多对象，不能保证少量对象保持同等外观。

`prepare` 按图像哈希、帧和工具版本缓存。`labels.json` 中 `text`、`box:[x,y,w,h]`、`font_size`、`font_family`、`color` 均为候选。置信度不能替代检查。核对后另存带 `reviewed:true` 的版本；可以编辑 `erase_polygon` 紧贴字形，`erase:false` 跳过不适合自动抹除的区域。

去字使用OpenCV inpaint，是待检查候选，可能损坏复杂背景。对照原图检查每处掩膜，必要时按已知底色修复或重建损坏图形，不自动生成式重绘整图。VTracer路线要求Alpha全255，否则停止；透明图直接语义重建 native opacity，或在用户接受指定背景后显式合成并记录。

`trace` 默认8位颜色精度、不删除小斑点、样条曲线、20,000路径预算。Python VTracer 0.6.15曲线拟合是近似，8位颜色精度不意味着像素无损。大于1600万像素先分区。

## 完整图理解

`understanding.json` 保存紧凑的实体、分区、关系（起点/终点/方向/激活或抑制）、标签、遮挡、不确定项。每项关联稳定ID。由代理对照原图填写，不能从转换结果反推后自证正确。不根据常识补画图中没有的关系。

## 修复与验收

1. `audit` 只证明输出对象结构。`compare` 不缩放、不自动对齐，尺寸不同即失败。源图长边超过1920时导出会缩放，需以源尺寸另行渲染或显式记录一致的比较尺寸。
2. 指标包括 RGB MAE、最大误差、差异像素比例，默认阈值0。不把大片空白导致的高像素一致率称为机制正确率。
3. 查看全图、叠加、最差局部，并检查所有文字、细线、连接及透明背景。模型只读取局部差异及简短清单；按稳定ID修改磁盘上的场景，不重写全部路径。
4. 默认最多三轮修复。重要缺失或未支持效果仍在时列为未达标。没有实际Cell-LCT同图结果，不能称效果等同。
5. `finalize` 使用配置中的 Presentations finalizer 输出新文件，并在工作区 `.ppp-validation` 保留记录。配置失效时重新安装，不跳过检查。验收针对最终文件，再运行 audit 并确认最终文件与已检查候选的一致性或重新渲染。`--render` 使用Artifact Tool重读已保存文件；实机验证需真正运行PowerPoint，不能混称。缺少Office时如实记录未验证。

## 参考与边界

参考 [Cell-LCT](https://github.com/yrui-cmd/cell-lct)，2026-09-09查阅。其公开流程面向Illustrator，包含文字记录/去除/恢复、SVG几何缓存和分批绘制，依赖外部服务及应用环境。PPP未接入其服务或密钥、未做同图对照，不能宣称等同。

本地工具使用 [VTracer](https://github.com/visioncortex/vtracer) 和 [RapidOCR](https://github.com/RapidAI/RapidOCR)。它们提供拟合和候选识别，不替代机制理解；成功的合成样例不证明所有真实图的性能。
