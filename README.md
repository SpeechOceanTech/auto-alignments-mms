# 长音频文本自动对齐

将一段音频和按句分行的文本对齐，生成包含每句起止时间的 CSV、Praat TextGrid 和制表符分隔文本。项目使用 MMS 多语种 CTC 模型与 uroman，提供本地网页、HTTP API 和命令行入口。

## 准备环境

需要 Python 3.9+、FFmpeg、Perl、互相匹配的 PyTorch 和 torchaudio（需包含 `torchaudio.functional.forced_align`，2.9 已移除）。其余 Python 依赖列于 [requirements.txt](requirements.txt)。根据机器的 CUDA 版本安装匹配的 PyTorch/torchaudio 后，安装其余依赖；模型和依赖不会在运行时自动下载。

确认下载后，可在已选好的 Python 环境中使用 `no-proxy pip install -r requirements.txt` 安装依赖。本机已有的 `/data/duhu/anaconda3/envs/qwen3-asr-semantic/bin/python` 配合下方本地模型路径已用于真实模型的单句测试，无需再次下载模型。

需要一个本地 MMS CTC 多语种 uroman 模型 `model.pt` 和对应的字典文件 `ctc_alignment_mling_uroman_model.dict`（或 `dictionary.txt`）。本机原有文件可以直接使用：

```bash
export MMS_MODEL_PATH=/data/duhu/alignments/align_model/model.pt
# 可选：单独指定字典路径
# export MMS_DICTIONARY_PATH=/path/to/dictionary.txt
```

默认使用可见的 CUDA 设备，否则使用 CPU。指定 GPU 时应使用物理设备编号，并注意 CUDA 会将可见设备重新编号。例如仅使用物理 GPU 4：

```bash
export CUDA_VISIBLE_DEVICES=4
export ALIGN_DEVICE=cuda:0
```

也可设置 `ALIGN_DEVICE=cpu`。仓库包含 uroman；若需使用其他副本，将 `UROMAN_PATH` 指向包含 `uroman.pl` 的 `bin` 目录。

## 输入与输出

文本文件使用 UTF-8，每个非空行是一句，也可使用 `ID<TAB>句子`。句子应与录音内容及顺序尽量一致；长句和与音频不一致的文本会影响效果。强制对齐不是语音识别，不会校正转写。数字和标点在对齐内部会被归一化，输出保留原文；无法归一化为有效字符的句子会报错。

CSV、文本的 `start` 和 `end` 单位均为秒，TextGrid 使用 `sentences` interval tier。处理流程与原脚本一致：转换为 16 kHz 单声道，使用 Silero VAD 检测语音，以 MMS 对齐文本，再根据静音区间修正句子边界。原脚本中的 ASR 识别和文字复核代码处于注释状态，不属于其实际执行流程。

常用语言可在网页中选择，也可输入三字母 ISO 639-3 代码，例如 `cmn`、`eng`、`jpn`；支持常见两字母代码和地区码（如 `zh_cn`、`en_us`）。自由输入只验证代码格式，不保证模型对所有语言的覆盖或准确性。语言信息参考 [MMS ISO 信息表](https://github.com/MXuer/mms-alignment-tools/blob/main/MMS_ISO_Information.md)。

## 网页和 API

```bash
python -m alignment_web.app
```

在服务器本机打开 `http://127.0.0.1:10076/`，或在同一网络的 MacBook 上打开 `http://服务器IP:10076/`。上传音频并填写文本或上传文本文件，选择语言后提交。任务单进程排队执行，可查看状态、输入和结果，下载三种格式，删除已完成或失败的任务。任务与文件默认保存在 `service_data/`；进程重启时未完成的运行中任务会标记失败，排队任务会继续。

默认监听所有网络接口，服务没有登录、权限隔离或用户配额。不要以多个服务进程共享同一任务目录运行。音频默认上限为 2048 MiB，文本上限为 2 MiB。可通过环境变量配置：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `ALIGN_WEB_HOST` | `0.0.0.0` | 监听地址 |
| `ALIGN_WEB_PORT` | `10076` | 监听端口 |
| `ALIGN_WEB_DATA_DIR` | `service_data` | 任务和上传文件存储目录 |
| `ALIGN_WEB_MAX_AUDIO_MB` | `2048` | 音频大小上限，单位 MiB |

接口文档位于 `/docs`。例如：

```bash
curl -X POST http://127.0.0.1:10076/v1/jobs \
  -F 'audio=@audio.wav' -F 'text_file=@sentences.txt' -F 'language=cmn'
curl http://127.0.0.1:10076/v1/jobs/JOB_ID
curl -O -J http://127.0.0.1:10076/v1/jobs/JOB_ID/artifacts/csv
```

也可以用 `text` 表单字段直接提交文本。`GET /v1/jobs` 列出任务，`GET /v1/languages` 返回常用语言，`DELETE /v1/jobs/{id}` 删除已结束任务及文件。服务需有足够的磁盘空间来保存上传内容和转换音频，清理任务会删除其输入和输出。

## 命令行

```bash
python align_cli.py audio.wav sentences.txt cmn output/
```

运行测试：`python -m unittest discover -s tests -v`。

使用本机 MMS 权重、PyTorch/torchaudio 和 GPU 可运行真实音频的端到端测试。

## 来源

核心流程参考本机 `auto_run.py`、`run.sh` 和 [MXuer/mms-alignment-tools](https://github.com/MXuer/mms-alignment-tools)，后者基于 Meta 的 MMS/fairseq 工具。内置 uroman 及许可见 `vendor/uroman/LICENSE.txt`：This project uses the universal romanizer software 'uroman' written by Ulf Hermjakob, USC Information Sciences Institute (2015-2020)。模型权重不包含在仓库中，使用时请遵守各上游项目及模型的许可。
