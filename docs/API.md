# 长音频文本对齐 API

服务默认使用 HTTP 端口 `10076`，以下示例以 `http://127.0.0.1:10076` 为地址；从其他设备访问时请替换为服务的实际地址。启动配置见 [README](../README.md)。启动服务后，也可访问 `/docs` 查看交互式 OpenAPI 文档。

## 认证与权限

`GET /health` 和 `GET /v1/languages` 无需登录。其他任务接口接受网页登录会话或管理员 API 密钥。普通用户只能访问自己的任务；管理员可查看所有任务，并可删除已完成或失败的任务。账号管理、密钥管理和统计接口要求管理员网页登录会话。

### 邮箱验证码与会话

1. `POST /api/auth/request-code`：JSON 参数 `email` 可填写企业邮箱用户名或完整的 `@dataoceanai.com` 地址。服务返回统一提示，不能从响应判断账户是否存在或邮件是否已送达；请求有频率限制。
2. `POST /api/auth/verify-code`：JSON 参数 `email`、`code`。成功后首次验证自动创建账户，响应包含 `user`、`csrf_token`，并设置 `alignment_session` HttpOnly Cookie。验证码有效期 10 分钟，只能使用一次；会话有效期 14 天。
3. `GET /api/auth/me`：获取当前会话的 `user` 和 `csrf_token`。
4. `POST /api/auth/logout`：注销当前会话，返回 `{"ok":true}`。

示例（使用自己的用户名和收到的验证码）：

```bash
BASE=http://127.0.0.1:10076
curl -X POST "$BASE/api/auth/request-code" \
  -H 'Content-Type: application/json' -d '{"email":"YOUR_USERNAME"}'
curl -c cookies.txt -X POST "$BASE/api/auth/verify-code" \
  -H 'Content-Type: application/json' -d '{"email":"YOUR_USERNAME","code":"YOUR_CODE"}'
curl -b cookies.txt "$BASE/api/auth/me"
```

使用会话进行 POST、PATCH、DELETE 等写操作时，除 Cookie 外还必须发送 `X-CSRF-Token: <csrf_token>`。如果请求含 `Origin` 头，其来源须与服务的 Host 一致；验证码请求也要求同源。API 密钥不需要 CSRF 头。

### API 密钥

管理员使用浏览器登录后，可在网页创建密钥，或通过会话接口管理；普通用户不能访问密钥管理页面和接口：

| 方法与路径 | 说明 |
| --- | --- |
| `GET /api/auth/api-keys` | 列出当前账号的密钥元数据，响应 `{"keys":[...]}`，不含明文 |
| `POST /api/auth/api-keys` | JSON `{"name":"名称"}`，名称为 1–100 个字符；响应 `{"key":{...},"token":"align_..."}` |
| `DELETE /api/auth/api-keys/{key_id}` | 撤销当前账号的密钥，响应 `{"ok":true}` |

创建密钥的响应仅在创建时返回明文，请妥善保存。后续任务请求使用：

```http
Authorization: Bearer <API_KEY>
```

密钥仅在所属账号是启用状态的管理员时可用。账号降为普通用户后，其已有密钥不能用于认证；再次成为管理员后，未撤销的密钥可继续使用。密钥管理、用户管理及统计接口只接受管理员网页登录会话，不能使用 Bearer 密钥调用。请求同时提供 Authorization 和 Cookie 时，以 Authorization 为准。

## 输入与语种

`GET /v1/languages` 返回 `{"languages":[...]}`；每项包含 `code`、具体语种或变体的 `name`、`iso`、`english`、`aliases`，以及兼容字段 `language_name`、`region`。例如 `zh_cn` 对应普通话，`ar_001` 对应现代标准阿拉伯语，`ar_eg` 对应埃及阿拉伯语。提交任务可使用列表中的代码、语言名称或别名，也可输入原有地区代码和三字母 ISO 639-3 代码。未列入列表的代码通过格式校验不代表模型必然支持。

文本使用 UTF-8（可带 BOM），每个非空行是一句；也支持 `ID<TAB>句子`。对齐时忽略 `【】` 内的标注，结果保留原文；这不是语音识别，文本应与录音内容和顺序一致。

`POST /v1/language-check` 可在提交前检查语种，JSON 为 `{"language":"en_us","text":"..."}`，需要认证和非空语种。返回 `status`：`match`（文本特征与所选语种一致）、`mismatch`（疑似不一致）或 `uncertain`（无法可靠判断），以及 `selected_language`、`detected_language`、`detected_name`、`message`。这是本机离线辅助检查，短文本、相近语种、混合语言和模型未覆盖的语种可能无法判断。该接口不会创建任务；调用方可根据结果提示用户并决定是否继续提交。批量网页上传会在提交前调用此接口；直接调用任务提交 API 时，调用方需自行检查。

## 创建与查询任务

### `POST /v1/jobs`

`multipart/form-data` 字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `audio` | 是 | 音频文件，扩展名支持 `.wav`、`.mp3`、`.flac`、`.m4a`、`.ogg`、`.opus`、`.aac`、`.webm` |
| `language` | 是 | 例如 `zh_cn`、`en_us` 或支持的语种名称 |
| `text` | 二选一 | 直接提交的逐句文本 |
| `text_file` | 二选一 | UTF-8 文本文件；与非空 `text` 不能同时提交 |
| `batch_id` | 否 | 批次 ID；批量提交时必填，且必须上传与清单匹配的 `text_file` |

默认音频上限 2048 MiB，可通过服务配置修改；文本上限 2 MiB。音频在请求期间转换为 16 kHz 单声道 WAV，转换完成并进入队列后才返回 `202`；新任务只保留转换后的音频。任务执行是异步的，返回队列状态并不代表对齐完成。

```bash
curl -X POST "$BASE/v1/jobs" \
  -H "Authorization: Bearer $ALIGN_API_KEY" \
  -F 'audio=@audio.wav' -F 'text_file=@sentences.txt' -F 'language=zh_cn'
```

响应示例：

```json
{"job_id":"0123456789abcdef0123456789abcdef","status":"queued"}
```

### `GET /v1/jobs`

列出当前用户可见的任务。查询参数均可选：

| 参数 | 说明 |
| --- | --- |
| `limit`、`offset` | 默认 `50`、`0`；`limit` 限制在 1–200，`offset` 不小于 0 |
| `status` | `queued`、`running`、`completed`、`failed` |
| `language` | 语言名称或代码；与规范地区代码及旧版 ISO 代码匹配 |
| `q` | 音频文件名或任务 ID 的子串 |
| `created_from`、`created_to` | `YYYY-MM-DD`，起止日期均包含当天；数据库任务时间使用 UTC |
| `owner_id` | 仅管理员可指定；`__legacy__` 表示无主的旧网页任务 |
| `batch_id` | 返回指定批次内的任务 |

响应格式 `{"jobs":[...],"total":0,"limit":50,"offset":0}`。任务记录包括 `id`、`language`、`audio_name`、`status`、`created_at`、`updated_at`、`error`、`owner_id` 和 `artifacts`；管理员列表额外包含 `owner_username`。按创建时间倒序排列。

### 批量上传和批次下载

批量接口逐对上传音频和文本，每条音频继续适用单任务上传上限；语种必须明确提供。文件按去除扩展名的名称匹配，忽略大小写并进行 Unicode 规范化。音频只支持单任务列出的格式，文本文件须为 `.txt`。重复名称的组不会匹配；最多提交 1000 对文件。

1. `POST /v1/batches/check` 发送 JSON 清单，例如 `{"audio_names":["a.wav","b.wav"],"text_names":["a.txt"],"language":"zh_cn"}`。返回 `pairs`（每项为 `{"audio":"a.wav","text":"a.txt"}`）、`unmatched_audio`、`unmatched_text` 和 `duplicates`。重复项包含 `stem`、`audio`、`text` 列表。检查不上传文件，也不创建任务。
2. `POST /v1/batches` 发送相同清单及必填 `language`，返回相同的配对信息和 `batch_id`；至少须有一对匹配文件。未匹配和重复文件不进入该批次。
3. 对每一对，调用 `POST /v1/jobs`，以 multipart 上传 `audio`、`text_file`、`language` 和 `batch_id`。文件名须与批次清单完全一致，语种须与批次一致。重复提交同一对返回已有任务 ID，避免重复排队。各对任务分别排队，已成功提交的任务不受其他对上传失败影响。
4. `GET /v1/batches` 返回可见批次及 `total`、`unsubmitted`、`queued`、`running`、`completed`、`failed` 数量；管理员的批次记录还包括 `owner_username`。`GET /v1/jobs?batch_id=<id>` 查询批次内任务，支持现有分页。
5. `GET /v1/batches/<id>/artifacts.zip?formats=csv` 下载该批次所有已完成任务的结果，支持 `csv`、`textgrid`、`txt` 及逗号组合；尚未完成或失败的任务不会包含在压缩包中，批次尚无已完成任务时返回 `409`。普通用户只能访问自己的批次，管理员可查看和下载所有批次。

### `GET /v1/jobs/{job_id}`

获取任务状态与可用结果格式。任务 ID 为创建时返回的完整 32 位 ID。轮询直到 `status` 为 `completed` 或 `failed`；失败时 `error` 包含错误信息。已完成任务的 `artifacts` 列出实际存在的 `csv`、`textgrid`、`txt` 文件。

```bash
curl -H "Authorization: Bearer $ALIGN_API_KEY" "$BASE/v1/jobs/$JOB_ID"
```

### `POST /v1/jobs/{job_id}/retry`

重试失败的任务，音频及输入文本必须仍存在；返回任务对象。其他状态返回 `409`。同一个任务重试成功在累计统计中只计一次。

### `DELETE /v1/jobs/{job_id}`

仅管理员可删除已完成或失败的任务及其文件，成功返回 `{"deleted":"<job_id>"}`；排队中和运行中任务返回 `409`。管理员既可使用会话，也可使用其 API 密钥。删除的任务不再计入统计。

## 结果、输入文件与波形

以下接口都要求任务可见：

| 方法与路径 | 说明 |
| --- | --- |
| `GET /v1/jobs/{job_id}/sentences` | 已完成任务的句子数组；每项为 `{"id":"1","start":0.12,"end":1.34,"text":"原始文本"}`，时间单位为秒 |
| `GET /v1/jobs/{job_id}/artifacts/{kind}` | 下载 `csv`、`textgrid` 或 `txt`，文件以原音频名命名；仅已完成且文件存在时可下载 |
| `GET /v1/jobs/{job_id}/input/audio` | 获取保存的音频；新任务为转换后的 WAV，旧任务可能保留原格式 |
| `GET /v1/jobs/{job_id}/input/text` | 获取原始文本 |
| `GET /v1/jobs/{job_id}/waveform` | 获取波形包络，`points` 默认为 4000，可取 1–48000 |

波形示例：

```json
{"duration":1.5,"peaks":[[-0.3,0.4],[-0.2,0.1]]}
```

`duration` 为秒；`peaks` 是按时间均分的每段最小、最大采样幅度，归一化到约 `[-1, 1]`，实际段数不超过音频采样数。波形无法读取时返回 `422`。

CSV 使用 Adobe Audition 标记格式：UTF-8、制表符分隔，列依次为 `Name`、`Start`、`Duration`、`Time Format`、`Type`、`Description`；`Start` 是开始时间，`Duration` 是持续时间，格式为 `时:分:秒.微秒`，`Time Format` 为 `decimal`，`Type` 为 `Cue`，`Description` 为句子原文。以前生成的任务在下载时也会转换成该格式。TXT 的 `start`、`end` 单位为秒；TextGrid 包含 `sentences` 层。下载 CSV 示例：

```bash
curl -OJ -H "Authorization: Bearer $ALIGN_API_KEY" \
  "$BASE/v1/jobs/$JOB_ID/artifacts/csv"
```

### 批量下载

`GET /v1/jobs/bulk-artifacts.zip` 返回 ZIP。参数 `job_ids` 为逗号分隔的 1–200 个任务 ID，`formats` 为逗号分隔的结果格式，默认 `csv`。所有任务须可见且已完成，所有指定文件须存在；压缩包不含目录，同名文件会自动加序号。

```bash
curl -G -o results.zip -H "Authorization: Bearer $ALIGN_API_KEY" \
  --data-urlencode "job_ids=$JOB_ID_1,$JOB_ID_2" \
  --data-urlencode 'formats=csv,textgrid,txt' "$BASE/v1/jobs/bulk-artifacts.zip"
```

## 管理员接口

以下接口均要求管理员**网页登录会话**；写操作还须携带 CSRF 头。

| 方法与路径 | 说明 |
| --- | --- |
| `GET /api/admin/users` | 返回 `{"users":[...]}`，包含用户 ID、用户名、邮箱、角色和状态 |
| `PATCH /api/admin/users/{user_id}` | JSON 中提供 `is_active` 和/或 `is_admin` 布尔值；返回 `{"user":{...}}`。不能停用或降级当前账号，停用会注销该账号的会话 |
| `GET /api/admin/usage` | 返回任务累计统计、当前状态及语种和用户分布 |

统计响应主体示意：

```json
{
  "totals":{"jobs":2,"completed":2,"language_count":1,"audio_seconds":120.0,
            "audio_duration_sample_count":2,"sentence_count":20,"sentence_sample_count":2},
  "current":{"queued":0,"running":0,"completed":1,"failed":0},
  "languages":[{"language":"zh_cn","jobs":2,"audio_seconds":120.0,
                "audio_duration_sample_count":2,"sentence_count":20,"sentence_sample_count":2}],
  "users":[{"owner_id":null,"username":"历史任务","jobs":2,"audio_seconds":120.0,
            "audio_duration_sample_count":2,"sentence_count":20,"sentence_sample_count":2}]
}
```

`totals` 及分组统计当前已完成的系统任务（包括网页和 API 提交），已删除任务不计入；`current` 按状态统计现有任务。语种和用户分布按已知音频总时长降序排列，时长未知的分组排在后面。语种覆盖数按模型 ISO 归并，语种分布保留地区代码。时长和句数仅统计已取得相应数据的样本，覆盖数分别为 `audio_duration_sample_count`、`sentence_sample_count`；本系统已有任务在启动后后台回填，缺失值不计入总和。旧流程的离线日志不计入统计。

## 错误和状态码

常见错误响应为 `{"detail":"错误说明"}`；参数格式验证也可能返回 FastAPI 的结构化 `detail` 数组。

| 状态码 | 常见原因 |
| --- | --- |
| `400` | 无效语种、文本、验证码、筛选条件或输入音频 |
| `401` | 未登录、会话失效或 API 密钥无效 |
| `403` | 权限不足、需要会话、CSRF 或 Origin 校验失败 |
| `404` | 任务、文件、账号或密钥不存在，或任务对当前用户不可见 |
| `409` | 任务状态不允许当前操作 |
| `413` | 上传音频或文本超过大小限制 |
| `422` | 请求参数验证失败，或波形不可读取 |
| `500` | 服务内部错误或结果文件格式无效 |
| `503` | 账户服务未配置或验证码邮件发送失败 |
