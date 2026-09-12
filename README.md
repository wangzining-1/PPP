# PPP — Pixel to PPT Path

![version](https://img.shields.io/badge/version-3.0-blue)
![license](https://img.shields.io/badge/license-MIT-green)
![graphics](https://img.shields.io/badge/native_graphics-%E2%89%A41000-brightgreen)
![platform](https://img.shields.io/badge/platform-Windows%20%2B%20Codex-lightgrey)

把科研机制图重建为 PowerPoint **原生分组、可编辑路径和真实文字**。先理解、后描摹；忽略背景，图形总数最多 1000。PPP 原名 GaphicAI。

## 特性

- 四角背景洪填与语义遮罩保护，保留浅色主体。
- 先输出一行计划 JSON；用户确认后才生成完整矢量。输入改变使计划失效。
- 2–4 倍边缘场分析、0.5 px 简化与坐标吸附、三次贝塞尔几何。
- 原生 PPT 组；组内图形递归计数，引用不会绕过 1000 上限。
- 组级颜色表、默认色、重复几何定义及 `ref`/`at` 实例。
- 保存后重读渲染、400% 预览及独立预算审计。

**边界**：本项目需要 Windows、PowerShell 和 Codex 提供的工作区运行时。Python 图像计算本地运行，语义理解仍由模型完成；它不是全离线模型。不能保证任意图像的完美语义分割或像素一致。400% 无连续同向台阶是验收要求，几何检查通过不代表整张渲染图通过。

## 快速开始

```bash
git clone https://github.com/wangzining-1/PPP.git
cd PPP
```

在 Codex 中取得工作区依赖路径（`load_workspace_dependencies`），然后在 PowerShell 执行：

```powershell
.\ppp\scripts\setup.ps1 `
  -PythonExecutable '<bundled python.exe 的绝对路径>' `
  -NodeExecutable '<bundled node.exe 的绝对路径>' `
  -NodeModules '<bundled node_modules 的绝对路径>' `
  -PresentationSkillDirectory '<Presentations skill 的绝对路径>'
```

安装器建立独立 venv、安装固定版本依赖、部署 `ppp` 技能并运行诊断。`@oai/artifact-tool`、Codex、Office 不包含在 MIT 发布包中，不能通过普通 `npm install` 推定获得这些宿主组件。首次安装需要联网下载 Python 依赖；图片不会上传至第三方矢量化服务。

## 使用示例

```text
使用 $ppp 将附件机制图重建为可编辑 PPT。先只给一行计划 JSON，
我确认后再生成；忽略背景，图形≤1000，按400%边缘标准逐项验收。
```

先由代理阅读原图、核对 OCR，生成去字图和经审查的互斥语义遮罩。配置见 [预算流程](ppp/references/budget-vectorization.md)。命令中的路径均为示例：

```powershell
$runner = Join-Path $env:USERPROFILE '.codex/skills/ppp/scripts/run.ps1'
& $runner budget plan graphics.png semantic.json
# 输出一行 {"plan":"...","units":...,"max_shapes":1000,"ss":3,"grid":0.5,"status":"awaiting_confirmation"}
# 等用户确认这份计划，再使用该 plan 标识。CLI 参数是调用者的确认声明，不是身份认证。
& $runner budget build graphics.png semantic.json work/budget --confirm-plan '<plan 标识>'
& $runner budget pptx text-template.pptx work/budget work/candidate.pptx
& $runner budget audit work/candidate.pptx
& $runner render work/candidate.pptx work/preview.png --scale 4
& $runner finalize '<工作区绝对路径>' '<候选绝对路径>' '<新的最终PPT绝对路径>'
```

`text-template.pptx` 必须是同尺寸单页原生 PPT，文字为顶层未填充文本框。可使用 `export` 从仅含已核对文字的 scene 生成。不要嵌入原图作为替代输出。所有输出使用新路径。

## 可调参数

| 参数 | 默认 | 范围与含义 |
| --- | --- | --- |
| `--max-shapes` | 1000 | 1–1000；按展开后的图形路径计数 |
| `supersample` | 3 | `semantic.json` 中 2、3 或 4 |
| `background_tolerance` | 18 | 背景模型的最大 RGB 通道偏差 |
| `background_model` | 四角插值 | 可指定同尺寸 RGB PNG 模型 |
| `background_seeds` | 四角 | 仅使用真实背景入口 |
| `units[].colors` | 6 | 起始组内调色板大小，最多32 |
| `units[].protected` | false | 禁止预算强制削减该组颜色 |
| 坐标网格 | 0.5 px | 固定；输出最多1位小数 |
| `render --scale` | 1 | 1、2、3、4；400%验收用4 |

配色当前使用主色块近似，不承诺原生渐变拟合。抗锯齿同色接缝补偿使用 1 px 轮廓，主体边缘最多向外延伸 0.5 px；必须结合语义、前景误差和400%渲染复核，不能仅凭元素少判定合格。

## 目录结构

```text
PPP/
├── README.md
├── LICENSE
├── ppp/
│   ├── SKILL.md
│   ├── agents/openai.yaml
│   ├── requirements.lock
│   ├── references/
│   └── scripts/
└── tests/
```

## 测试与验收

```powershell
& '<PPP venv python.exe>' -m unittest discover -s tests -p 'test_*.py' -v
```

测试覆盖背景、预算、遮罩、细线、原生组/文字、贝塞尔/网格、复用引用与拒绝超预算展开。最终还必须查看保存后渲染、未归属前景和全部机制关系。`edge_400_percent: pending` 不能写成验收通过。PowerPoint 桌面编辑只有实际执行后才能标为验证。

## 发布到 GitHub

在 GitHub 创建空仓库 PPP，先确认暂存区不含运行配置、图片、输出或凭据：

```bash
git init -b main
git add README.md LICENSE .gitignore ppp tests
git diff --cached --stat
git commit -m "PPP v3.0"
git remote add origin https://github.com/wangzining-1/PPP.git
git push -u origin main
```

提交需要本机 Git 身份与 GitHub 认证。目标仓库为 `wangzining-1/PPP`；已有 `origin` 时先核对，不能覆盖未知远端。

## License

[MIT](LICENSE)。第三方依赖及宿主应用各自遵循其许可证。
