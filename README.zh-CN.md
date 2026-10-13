# llmstxtdb skills

一个开源的 Agent Skill：帮编码助手**编写、检查、修复、部署** [`llms.txt`](https://llmstxt.org)——给语言模型看的文档索引文件。

它出自 **llmstxtdb**（llms.txt 文档索引站，会核验每个收录文件的可访问性、结构与链接有效性）。这个 skill 把同一套规则、同一套问题码装进了编码助手里。

[English](README.md)

## 能做什么

- **编写**：为项目或站点生成 llms.txt——选哪些页面、怎么排序、每条链接怎么描述。
- **检查**：用自带的零依赖脚本校验本地文件或线上地址。
- **修复**：按问题码修（`SPEC_H1_MISSING`、`SPEC_ENTRY_NOT_LINK`、`SPA_DETECTED`、`LINK_HEALTH` 等），每个码都说明为什么检查、怎么修、怎么验收。
- **排查部署**：`/llms.txt` 返回 404、返回了网页、类型不对、重定向成链。
- **相关文件**：子路径文件、逐页 Markdown 版本、`llms-full.txt`。

## 有什么不同

- **三件事分开说**：提案**要求**什么（只有一个 H1，其余很少）、文件**实际能不能用**（能取到、链接有效）、哪些只是**写得更好**。很多教程把自己的偏好说成「规范要求」。
- **与在线检查器同一套问题码**：本地脚本报的码和 llmstxtdb 报告里的码是同一个意思；两边用同一批样例做测试，精确到每个码出现的次数。
- **不夸大**：llms.txt 不会让任何 AI 产品读取、引用或优先展示你的站点，skill 明确要求助手不这样说。
- **脚本联网很谨慎**：只访问 http(s)、拒绝带凭据的地址、默认拒绝内网地址、逐跳复核重定向、最多读 2MB，每个请求放在子进程里由父进程按硬截止时间终止。

## 安装

用 `skills` 命令行（适用于 Claude Code、Codex 等支持 Agent Skills 的助手）：

```bash
npx skills add https://github.com/web-casa/llmstxtdb-skills --list          # 先看看有什么
npx skills add https://github.com/web-casa/llmstxtdb-skills --skill llmstxtdb
```

作为 Claude Code 插件：

```text
/plugin marketplace add web-casa/llmstxtdb-skills
/plugin install llmstxtdb@llmstxtdb-skills
```

手动安装：把整个 `skills/llmstxtdb/` 目录复制到助手的技能目录（Claude Code 是 `~/.claude/skills/` 或项目里的 `.claude/skills/`）。要复制整个目录，不要只复制 `SKILL.md`——参考文档和校验脚本都是 skill 的一部分。

**从 0.1.0 升级。** 0.2.0 起技能从 `llms-txt` 改名为 `llmstxtdb`，以免和其他讲 llms.txt 的技能混淆。安装前先把助手技能目录里旧的 `llms-txt` 目录删掉（或执行 `npx skills remove llms-txt`），否则助手会找到两份。调用名是 `/llmstxtdb`；作为 Claude Code 插件安装时是 `/llmstxtdb:llmstxtdb`。

## 使用

直接说：

- 「给这个文档站生成 llms.txt」
- 「检查一下 `public/llms.txt`」
- 「报告里有 65 处 SPEC_ENTRY_NOT_LINK，帮我修」
- 「`https://example.com/llms.txt` 返回的是网页，为什么？」

也可以自己运行脚本（Python 3.9+，只用标准库）：

```bash
python3 skills/llmstxtdb/scripts/validate_llms_txt.py public/llms.txt
python3 skills/llmstxtdb/scripts/validate_llms_txt.py https://example.com/llms.txt --check-links
python3 skills/llmstxtdb/scripts/validate_llms_txt.py public/llms.txt --json
```

规范未通过或部署检查失败时退出码为 `1`，可以直接放进 CI。

## 本地脚本与在线检查器的分工

脚本负责写文件时的本地循环：结构、建议，以及对单个线上地址的观测。llmstxtdb 在线检查器负责需要服务端的部分：整份文件的链接健康、变更追踪、字母评级与评级分。脚本**不输出评级**——评级以在线检查器公示的规则为准。

两边解析 Markdown 的方式不同（脚本按行，检查器用完整语法树）。`scripts/fixtures/strict/` 下的样例两边结果完全一致；少数写法特殊、结果不同的样例固定在 `scripts/fixtures/divergent/`，原因写在 `references/spec.md`。

## 问题码

中文版问题码参考：[`skills/llmstxtdb/references/error-codes.zh-CN.md`](skills/llmstxtdb/references/error-codes.zh-CN.md)（由检查器的修复手册生成）。

## 致谢

全部内容独立撰写，组织方式参考了以下 MIT 许可的项目（没有复制文字或代码）：

- [johnericforte/claude-skill-llms-txt](https://github.com/johnericforte/claude-skill-llms-txt)
- [cartoonitunes/inlay-skills](https://github.com/cartoonitunes/inlay-skills)
- [microsoft/skills](https://github.com/microsoft/skills)（`wiki-llms-txt`）

格式本身来自 Jeremy Howard 的 [llmstxt.org](https://llmstxt.org) 提案。

## 许可证

[MIT](LICENSE)
