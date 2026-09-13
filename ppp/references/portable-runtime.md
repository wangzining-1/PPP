# macOS / Linux / Windows 入口

`run.py` 使用 Python 标准库分派，不依赖 PowerShell。`mechanism` 单独运行不需要图像/OCR依赖；导出需要宿主提供的 Node、`@oai/artifact-tool` 和 `jszip`。原位图转换还需 requirements.lock 的图像/OCR依赖。官方一键 setup.ps1 仍为Windows入口。

先用宿主 `load_workspace_dependencies` 获取真实路径。在已安装skill根目录建立不入库的 `runtime.local.json`：

```json
{
  "python": "/absolute/path/to/ppp-venv/bin/python",
  "node": "/absolute/path/to/node",
  "node_modules": "/absolute/path/to/node_modules",
  "presentation_skill": "/absolute/path/to/presentations/skills/presentations",
  "presentation_python": "/absolute/path/to/bundled/python"
}
```

`presentation_skill` 用于 finalize，目录须含兼容的 container_tools。不要复制他人runtime配置。Node库由宿主提供，不要写入共享bundle。

按当前平台建立独立venv，安装仓库锁定依赖（版本在本机不可用时停止并报告，不静默改锁）：

```bash
python3 -m venv /absolute/path/to/ppp-venv
/absolute/path/to/ppp-venv/bin/python -m pip install -r <skill>/requirements.lock
python3 <skill>/scripts/run.py doctor
```

`doctor` 检查Python依赖及Node导入，不等于完整OCR模型初始化、Office实机测试或任意图片验收。可独立先用机制JSON生成场景，再配置导出。已安装skill在后续轮次可发现；如宿主尚未刷新列表，开启新任务。
