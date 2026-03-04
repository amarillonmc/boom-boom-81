# No81·AI大乱斗知识库（存档站）

这里是 No81 论坛 “AI大乱斗/斗蛐蛐” 相关内容的 Markdown 归档与索引站。

- **人类用法**：用左侧导航 + 搜索框浏览、检索。
- **LLM/Agent 用法**：不要全库扫；优先走索引，把 token 花在刀刃上。

---

## 给 LLM/Agent 的快速路线（强烈建议照做）

1. 先读索引（优先 JSONL）  
   - `index/topics.jsonl`  
   - `index/topics.csv`

2. 根据问题筛选 `category`  
   - `roles`：角色卡  
   - `rulebooks`：规则/框架  
   - `records`：已完结记录

3. 再根据 `author / title / topic_id` 定位 `file_path`，只打开匹配的 Markdown 文件。

> 你的目标是“最少文件 → 最大信息”，不是“把仓库当硬盘扫一遍”。

---

## 常用入口

### 角色卡
- **按作者浏览（推荐）**：`roles/by-author/index.md`

### 原始索引（机器友好）
- `index/topics.jsonl`
- `index/topics.csv`
- `index/authors.jsonl`
- `index/authors_roles_sample.jsonl`

---

## 备注

- 该站点通常不会包含图片/多媒体，仅保留文本与必要链接。
- 若未来出现 “spoiler 权限不足导致抓取缺失” 的情况，建议在 `kb/index/` 下额外生成并公开一份告警/缺失清单（比如 warnings.txt / warnings.jsonl），方便下游工具避坑。