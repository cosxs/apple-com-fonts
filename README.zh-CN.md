# Apple.com Fonts

[English](README.md) | 简体中文

发现、验证并归档 Apple 公开全球首页所引用的 Web 字体。

本项目每次运行都从 Apple 实时的国家和地区目录开始，不会把本地字体、已生成的清单、
历史快照、Apple Developer 下载包或操作系统字体作为发现数据源。

## 功能

- 从 Apple 官方目录发现当前国家和地区首页。
- 提取这些首页引用的 `/wss/fonts` 样式表。
- 探测 Apple 页面中已出现字体族的可用版本。
- 生成规范化 URL 列表和可审计的发现清单。
- 并发下载字体、验证文件签名并按确定性目录结构整理。
- 使用 GitHub Actions 同步已验证的字体集合并发布可复现的月度归档。

## 发现范围

Apple 没有为 `/wss/fonts` 提供公开目录索引。本项目所称的当前字体集合，是从以下来源
发现的全部唯一字体 URL：

1. Apple 的[国家和地区目录](https://www.apple.com/choose-country-region/)。
2. 该目录列出的所有唯一全球首页。
3. 对这些首页引用字体族进行版本探测后成功返回的结果。

此范围不表示能够覆盖未被链接的文件、仅在内页使用的字体、Apple Developer 下载包或
Apple 操作系统字体。每次运行都完全基于 Apple 实时公开来源；已有产物只作为输出，绝不
作为下一次发现的输入。

## 环境要求

- Python 3.14 或更高版本
- 克隆或提交仓库字体归档时需要 Git LFS

在 macOS 上安装 Git LFS，并为当前仓库初始化：

```bash
brew install git-lfs
git lfs install --local
```

## 快速开始

创建隔离环境，并安装项目及开发工具：

```bash
python3.14 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

只发现当前字体链接，不下载字体文件：

```bash
.venv/bin/apple-com-fonts discover
```

发现、下载、验证并整理当前字体集合：

```bash
.venv/bin/apple-com-fonts download
```

## 命令

### `discover`

写入一个新的带时间戳快照，其中包含：

- `font-urls.txt` — 规范化并去重的 Apple 字体 URL。
- `manifest.json` — 首页覆盖情况、样式表请求、版本探测、HTTP 元数据、失败记录、
  观测 URL 和来源信息。

```bash
.venv/bin/apple-com-fonts discover \
  --output snapshots/manual-discovery \
  --concurrency 16
```

### `download`

先运行发现流程，再下载得到的字体集合。已有且有效的文件会被跳过；缺失或无效的文件只有
在完整响应通过签名验证后才会被替换，临时下载文件通过原子移动写入最终位置。

```bash
.venv/bin/apple-com-fonts download \
  --fonts-dir fonts \
  --output snapshots/manual-download
```

目标目录由 Apple URL 路径确定：

```text
fonts/<family>/<version>/<format>/<file>
```

除发现产物外，`download` 还会写入 `downloads.json`，记录每个文件的状态、本地路径、
大小、HTTP 元数据和错误信息。

### 常用选项

| 选项 | 用途 |
| --- | --- |
| `--output PATH` | 将报告写入指定的新目录，而不是带时间戳的默认快照。 |
| `--proxy MODE` | 选择 `auto`、`env`、`none` 或显式代理 URL。 |
| `--timeout SECONDS` | 设置请求超时时间。 |
| `--concurrency COUNT` | 设置发现和下载的并发请求数。 |
| `--retries COUNT` | 设置瞬时失败的重试次数。 |
| `--fonts-dir PATH` | 为 `download` 指定字体目标目录。 |

默认的 `auto` 代理模式会先读取当前 macOS 系统代理，再读取标准代理环境变量。代理地址
不会写入生成的清单。

```bash
.venv/bin/apple-com-fonts discover --proxy 'http://127.0.0.1:PORT'
```

## 可靠性模型

- 无法获取或解析 Apple 官方地区目录时，发现流程立即停止。
- 单个首页或样式表失败会被记录，本地运行仍可生成可审计的部分结果。
- 手动下载不会删除最新发现结果中未出现的本地文件。
- 字体文件只有在签名验证通过后才会以原子方式写入。
- WSS 样式表请求使用对应 Apple 来源作为 `Referer`。
- 自动发布只有在首页、样式表和字体下载全部通过验证后，才允许镜像仓库字体归档。

## 自动发布

[Release 工作流](.github/workflows/release.yml)在每月第一天的 `00:00 UTC` 运行，也支持
手动触发。

一次完整成功的发现和下载完成后，工作流会：

1. 将已验证集合镜像到 `fonts/`，并删除不再被发现的文件。
2. 验证仓库中的每个字体文件都由 Git LFS 跟踪。
3. 仅在字体集合发生变化时提交并推送。
4. 构建可复现归档及其 SHA-256 校验文件。
5. 创建或更新当月的 `fonts-YYYY-MM` GitHub Release。

自定义 Release 资产为：

```text
apple-com-fonts-YYYY-MM.tar.gz
apple-com-fonts-YYYY-MM.tar.gz.sha256
```

归档中包含 `fonts/`、发现和下载元数据、`LICENSE`、`NOTICE` 以及两份 README。GitHub
会另外提供与标签对应的仓库源码归档。

工作流使用仓库标准的 `GITHUB_TOKEN`，并授予 `contents: write` 权限。仓库规则必须允许
GitHub Actions 将字体同步提交推送到默认分支。

## 项目结构

```text
.
├── .github/workflows/             # CI、月度同步与 Release
├── fonts/                         # 当前 Git LFS 字体归档
├── snapshots/                     # 本地生成的报告；Git 忽略
├── src/apple_com_fonts/           # 发现、网络与下载实现
├── tests/                         # 自动化测试
├── LICENSE
├── NOTICE
├── README.md
├── README.zh-CN.md
└── pyproject.toml
```

## 开发

在项目虚拟环境中运行完整质量检查：

```bash
.venv/bin/pyright
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
actionlint .github/workflows/release.yml
```

Pyright 以严格模式检查 `src` 和 `tests`。

[CI 工作流](.github/workflows/ci.yml)会在每次推送和拉取请求中运行依赖检查、Ruff、
Pyright，以及带分支覆盖率门槛的测试套件。

## 许可证与第三方内容

Copyright (c) 2026 cosxs.

项目原创源代码、测试、配置和自动化以 [MIT License](LICENSE) 发布。通过 Apple 公开
`/wss/fonts` URL 发现的字体文件不适用本项目的 MIT 许可证。来源、关联关系和第三方权利
说明请参阅 [NOTICE](NOTICE)。
