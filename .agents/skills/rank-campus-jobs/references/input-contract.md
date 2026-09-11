# 排名输入契约

生成运行 JSON 时遵守本文件。所有岗位必须来自同一家公司。

## 顶层结构

```json
{
  "company": {
    "name": "公司名称",
    "career_url": "官方校招入口"
  },
  "run": {
    "collected_at": "ISO-8601 时间",
    "collection_method": "api | html | browser | mixed | fixture（仅测试）",
    "pagination_complete": true,
    "list_job_count": 0,
    "detail_success_count": 0,
    "detail_failure_count": 0,
    "candidate_profile_refreshed_at": "候选人资料的 ISO-8601 刷新时间或版本",
    "performance_budget_ms": 90000,
    "errors": []
  },
  "profile_evidence": [],
  "company_evidence": [],
  "jobs": []
}
```

## 候选人证据

只保存匹配所需的脱敏单元，不保存飞书全文：

```json
{
  "id": "profile-1",
  "experience": "经历名称",
  "situation": "业务场景",
  "action": "本人动作",
  "mechanism": ["产品或 AI 机制"],
  "result": ["量化或定性结果"],
  "capabilities": ["能力标签"],
  "source": "resume | experience_file | feishu",
  "source_revision": "文档版本或刷新时间",
  "confidence": "high | medium | low"
}
```

## 公司与业务证据

```json
{
  "id": "company-1",
  "claim": "只陈述来源能够支持的事实",
  "url": "https://...",
  "published_at": "发布日期或获取日期",
  "scope": "company | business_line | product | role"
}
```

## 岗位结构

```json
{
  "id": "官网稳定 ID",
  "company": "与 company.name 完全一致",
  "title": "岗位名",
  "department": "部门或业务线，未知时写未知",
  "location": "地点，未知时写未知",
  "url": "官方详情页或可验证的官方列表页",
  "description": "岗位正文",
  "similar_group": null,
  "hard_requirements": {
    "campus_full_time": "pass | conflict | unknown",
    "graduation_year": "pass | conflict | unknown",
    "education": "pass | conflict | unknown",
    "major": "pass | conflict | unknown",
    "location_preference": "pass | conflict | unknown",
    "language_working_proficiency": "pass | conflict | unknown"
  },
  "signals": {
    "criterion_id": {
      "state": "strong | partial | conflict | unknown",
      "evidence": ["候选人、JD 或业务资料中的可核查事实"],
      "note": "可选说明"
    }
  }
}
```

只要任一硬条件为 `conflict`，岗位就不参加排名，但仍保留在全量数据和排除区。`unknown` 默认保留。

当候选人声明不具备英语工作能力时，JD 明确要求英语可作为工作语言、日常跨国协作或面向海外市场交付的，填写 `language_working_proficiency: conflict`。仅出现“英语优秀者优先”或职位标题带“国际化”时，填写 `unknown`，并在报告中提示人工核验；不能据此自动判为冲突。

## 评分子项

### 个人能力匹配（30）

- `personal_relevant_context`：相关业务或产品场景经历，8。
- `personal_owner`：端到端产品职责与 Owner 程度，7。
- `personal_ai_mechanism`：相关 AI 或产品机制经验，6。
- `personal_results`：可验证的量化结果，5。
- `personal_transfer`：产品或技术能力迁移，4。

### AI 落地深度（27.5）

- `ai_core`：AI 是否为产品核心能力，7.5。
- `ai_agent_workflow`：Agent、模型策略或 Workflow 参与深度，6.5。
- `ai_evaluation_loop`：评测、Badcase 与数据闭环，5.5。
- `ai_live_value`：真实上线和业务价值闭环，4.5。
- `ai_cross_function`：算法、工程和数据协同深度，3.5。

### 所属业务与岗位机会前景（27.5）

- `opportunity_growth`：业务线或产品增量空间，7.5。
- `opportunity_investment`：公司对该具体方向的近期投入，6.5。
- `opportunity_advantage`：独特场景、数据或生态优势，5.5。
- `opportunity_value_loop`：岗位可影响的价值闭环，4.5。
- `opportunity_differentiation`：差异化和出业绩空间，3.5。

### 岗位成长空间（15）

- `growth_zero_to_one`：0 到 1 或高速迭代机会，5。
- `growth_scope`：职责边界和决策参与度，4。
- `growth_complexity`：跨团队和问题复杂度，3。
- `growth_visibility`：结果可见性和出业绩空间，3。

## 状态解释

- `strong`：证据直接、充分支持该子项，取得满分。
- `partial`：证据部分支持或能力可迁移，取得 50%。
- `conflict`：存在明确反向证据，取得 0 分。
- `unknown`：证据不足；保守分不计分，理论上限保留该项全部权重。

除 `unknown` 外，状态没有非空 `evidence` 时，核心会按 `unknown` 处理。
