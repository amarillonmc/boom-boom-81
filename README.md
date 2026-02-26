# boom-boom-81

No81·AI大乱斗知识库（角色卡 / 规则书 / 已完结记录）

这个仓库是 `number81.xyz` 论坛内容的本地 Markdown 归档，主要用途：
- 人类阅读与存档
- 直接提供给 LLM / LLM Agent 做检索、总结、对比分析

## 给 LLM/Agent 的快速说明（优先读）

如果你是一个要回答用户问题的 LLM/Agent，请按这个顺序工作：

1. 先看索引：`kb/index/topics.csv` 或 `kb/index/topics.jsonl`
2. 根据问题类型筛选 `category`
   - 角色相关：`roles`
   - 规则相关：`rulebooks`
   - 对局表现/记录相关：`records`
3. 根据 `title`、`author`、`topic_id` 定位目标文件 `file_path`
4. 再读取对应 Markdown 正文，不要先全库扫全文

这能显著减少 Token 消耗与噪音。

---

## 仓库结构

```text
kb/
  roles/               # 角色卡主题（来自 topic=1378.0 的链接）
  rulebooks/           # 规则书主题（board=15）
  records-completed/   # 已完结记录（board=14;prefix=3）
  index/
    topics.csv         # 人类可读索引
    topics.jsonl       # 机器友好索引
    warnings.txt       # 抓取告警（如 spoiler 权限）

tools/no81_sync/
  sync.py              # 抓取与转换脚本
  requirements.txt
  config.example.env
  README.md

doc/
  no81-kb-plan.txt
  no81-kb-implementation-log.txt
```

---

## 数据文件格式

每个主题对应一个 Markdown 文件（整帖导出，按楼层顺序），开头带 YAML 元数据：

```yaml
topic_id: 3333
title: "20260217-新年新蛐蛐"
category: "records"
source_url: "https://number81.xyz/index.php?topic=3333.0"
author: "Justfish"
created_at: "二月 16, 2026, 11:35 上午"
fetched_at: "2026-02-26 10:30:00 +0800"
```

正文结构示例：

```md
## 1F
- Author: Justfish
- Posted at: 二月 16, 2026, 11:35 上午

正文...
```

---

## 常见问题到路径的映射

- “总结作者 X 的角色设计风格”
  - 先查 `kb/index/topics.*` 中 `category=roles` 且 `author=X`
  - 再读取对应 `kb/roles/*.md`

- “角色 Y 在每次乱斗中的表现”
  - 先查 `category=records`
  - 在 `title` 与正文中定位角色名 Y
  - 主读 `kb/records-completed/*.md`

- “模型/规则在大乱斗中常见问题”
  - 主读 `kb/rulebooks/*.md`（规则定义）
  - 辅读 `kb/records-completed/*.md`（实战体现）

---

## 部署与使用（同步脚本）

1. 复制配置模板：

```bash
cp tools/no81_sync/config.example.env tools/no81_sync/.env
```

2. 编辑 `tools/no81_sync/.env`，填写 SMF 账号（需要可见 spoiler 的权限）。

3. 安装依赖：

```bash
python -m pip install -r tools/no81_sync/requirements.txt
```

4. 执行同步：

```bash
python tools/no81_sync/sync.py
```

可选参数：

```bash
python tools/no81_sync/sync.py --category roles
python tools/no81_sync/sync.py --category rulebooks
python tools/no81_sync/sync.py --category records
python tools/no81_sync/sync.py --dry-run
```

---

## 抓取范围定义

- 角色卡：`https://number81.xyz/index.php?topic=1378.0` 中的全部主题链接
- 规则书：`https://number81.xyz/index.php?board=15.0` 全分页主题
- 记录：`https://number81.xyz/index.php?board=14.0;prefix=3` 全分页主题

---

## 注意事项

- 本仓库不下载图片/多媒体，仅保留文本与必要链接。
- 若账号权限不足，spoiler 可能导出为提示文本；详见 `kb/index/warnings.txt`。
- 时区按论坛本地时间（UTC+8）写入 `fetched_at`。
