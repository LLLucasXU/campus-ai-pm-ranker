# Campus AI PM Ranker

面向中国公司校招官网的 AI 产品经理岗位筛选 Skill。它在**同一家公司**的校招岗位池中，结合候选人的简历或过往经历，给出可复核的岗位优先级，而不把分数解释为跨公司比较或录用概率。

## 能做什么

- 遍历公司官方校招官网中的产品类岗位与职位详情；
- 筛选 AI 产品经理、Agent PM、AI Native PM 及相近产品岗位；
- 输出保守推荐 Top 3，最多附带 1 个高潜破格推荐；
- 给出第 4–10 名的简表、官方链接、评分证据与人工核验项；
- 保留相似但不同的 JD，不会因为标题相近而合并或删除。

## 使用边界

适用于单家公司、校招官网、产品类岗位的筛选。它不做跨公司统一排名，不处理 BOSS 直聘等单 JD 聚合平台，也不自动投递或绕过登录、验证码和访问限制。

## 安装与使用

将仓库克隆到本地，并在仓库根目录打开 Codex。Skill 位于 `.agents/skills/rank-campus-jobs/`，评分核心位于 `src/`；请保留这两个目录的相对位置。

```bash
git clone https://github.com/LLLucasXU/campus-ai-pm-ranker.git
cd campus-ai-pm-ranker
```

之后可直接在该项目中提出示例请求，或显式调用 `$rank-campus-jobs`。

## 开始前：提供候选人资料

第一次使用时，请至少提供以下一项：

1. 简历文件：PDF、DOCX、Markdown 或文本；
2. 过往经历资料：本地 Markdown/文本，或你有访问权限的飞书文档链接。

两项同时提供时会联合使用。若两项都没有，Skill 会停止个性化排名并请求资料，不会基于假设编造匹配结论。

可将本地资料放在 `candidate/`：

```text
candidate/
├── resume.pdf
├── experience.md
└── candidate-profile.local.yaml
```

从 [candidate-profile.example.yaml](candidate-profile.example.yaml) 复制配置模板。`candidate/`、`*.local.yaml`、临时输入和运行报告都已写入 `.gitignore`，不会被默认提交。

如果经历资料是飞书文档，Skill 仅在本次运行中通过本地 `lark-cli` 读取你明确提供且有权访问的链接；不会将经历全文或链接写入公开仓库。

## 首次校准（可选）

除候选人资料外，可以一次性补充以下偏好；未填写则使用默认 AIPM 校招筛选标准：

- 目标方向：AI 应用、Agent、AI Native、平台或泛产品；
- 偏好业务：C 端、企业服务、内容社区、研发效能、具身智能等；
- 是否接受平台/中台岗位；
- 地点、工作语言、行业等硬条件；
- 对 AI 深度、业务前景和成长空间的额外偏好。

## 默认评分模型

| 维度 | 权重 | 判断重点 |
| --- | ---: | --- |
| 候选人经历匹配 | 30 | 场景、职责、产品机制、成果的可迁移性 |
| AI 落地深度 | 27.5 | AI 是否核心、Agent/模型/评测闭环、真实价值 |
| 业务与岗位机会前景 | 27.5 | 增长、投入、独特优势、个人业绩可见性 |
| 岗位成长空间 | 15 | 0 到 1、职责范围、复杂度、成果可见性 |

平台/中台岗位不会因为名称被直接扣分，但会重点判断个人是否能拥有可衡量、可归因的结果。若某岗位经历匹配和 AI 深度极高、但业务机会证据不足，Skill 可将其标为高潜破格推荐，并明确列出需要人工核验的事实。

## 示例请求

```text
使用 $rank-campus-jobs 筛选一家公司校招官网中的 AI 产品岗位。

公司：示例科技
官网：https://careers.example.com/campus
简历：candidate/resume.pdf
经历：candidate/experience.md
偏好：优先 AI Agent 与 C 端 AI 应用；不接受需要英语作为工作语言的岗位。
```

## 输出

每次完成后会生成：

- `report.md`：中文筛选报告；
- `ranking.csv`：全量岗位排名；
- `performance.json`：采集与生成耗时；
- `run-summary.json`：筛选、分页和详情完整性；
- 供人工复核的脱敏证据与岗位数据。

正式投递前，仍应人工核查官网状态、硬条件与 JD 原文。

## 隐私与安全

- 本仓库不包含真实候选人的简历、姓名、联系方式、飞书链接或经历全文；
- 不提交 `candidate/`、本地偏好、`tmp/`、`runs/` 和访问凭证；
- 仅保留完成匹配所需的脱敏证据摘要；
- 登录、验证码或权限限制出现时，会请求用户操作，不尝试绕过。

## 开发验证

项目不依赖第三方 Python 包。可在仓库根目录运行：

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
