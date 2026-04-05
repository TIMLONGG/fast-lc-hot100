---
name: update_leetcode_record
description: 解析当天的 LeetCode 刷题 Jupyter Notebook 文件内容，提取刷题记录并格式化追加到 README.md 的 timeline 列表中。
---

# update_leetcode_record

此技能用于指导大模型读取用户当天的刷题记录 Jupyter Notebook 文件（`.ipynb`），分析代码及其附带的注释，提取指定的进度和复习标记，并将其整理成规范的 Markdown 列表项，追加到项目根目录下的 `README.md` 文档中。

## 🎯 任务内容提取规则

当用户提供了一个 `.ipynb` 的文件内容或路径时，你需要自动提取出如下 4 方面的内容：

1. **题目信息与难度 (Difficulty)**：
   - 提取题号与题目名称（如 `# 42. 接雨水` 提取出 `42. 接雨水`）。
   - 将行内单独字母表示的难度（如：`# E`、`# M`、`# H`）翻译成 `Easy`、`Medium`、`Hard`。
2. **通过情况 (状态提取)**：
   - 根据缩写标记和括号说明提取状态，**必须使用全称**而不是字母缩写。
   - `P` -> `Pass`（通过）
   - `R` -> `Review`（需要复习）
   - `A` -> `Again`（再次解答通过）
   - 如果有括号补充说明（如解法），追加在全称后面，示例：`# P(遍历两次) R(遍历一次)` 提取为 `Pass(遍历两次), Review(遍历一次)`。
3. **力扣网站对应题目链接 (LeetCode URL)**：
   - 推测并补全题目在力扣的中文站链接：比如 `42. 接雨水` 推导成 `https://leetcode.cn/problems/trapping-rain-water/`。

## 📝 追加生成的 Markdown 格式规范

请将提取出的信息合并为一条极致简洁的 Markdown 列表项，并追加到 `README.md` 的所在日期标题下（如 `### 2026.04.02`）。

**列表项格式必须如下：**
`- **[题号]. [题目名称]** | \`[难度]\` | [状态，如: Pass, Review(遍历一次)] | [🔗 LeetCode]([力扣链接])`

*(注：不需要在这里记录详细的长篇复习建议，保持 timeline 的清爽明了即可！)*

---
### 🌟 示例参考

若你看到了这样一段 `.ipynb` 的内容（节选）：
```python
# 42. 接雨水
# H
# P(遍历两次) R(遍历一次)
class Solution:
...
# 我的解法依然是第一次做这道题时想到的遍历两次，但是总归得掌握最优解法。
# 前后缀分解是前置算法，虽然需要遍历三次，但掌握之后可以更好地理解双指针遍历一次的解法。
```

同时你得知其为 `2026.04.02` 的记录，你需要为 `README.md` 追加如下变更：

```markdown
### 2026.04.02
- **42. 接雨水** | `Hard` | Pass(遍历两次), Review(遍历一次) | [🔗 LeetCode](https://leetcode.cn/problems/trapping-rain-water/)
```

## 🛠️ 工作流执行标准
1. 使用 `view_file` 工具查看 `.ipynb` 的全量内容（如 Notebook 的源 JSON）。
2. 在大脑里完成上述信息的提取和逻辑分析。
3. 随后查看 `README.md` 文件，判断属于哪一天的 `timeline`，并在对应日期下面拼接格式化的列表项。
4. 使用恰当的文件修改工具（如 `multi_replace_file_content` 或 `replace_file_content`）去**修改并保存** `README.md`。务必确认更新已写入硬盘，且符合严格的 Markdown 语法不会破坏原有排版。
5. 操作完成后，告知用户追加成功。
