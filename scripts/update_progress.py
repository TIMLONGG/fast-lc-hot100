#!/usr/bin/env python3
"""
Progress 生成器 v4.1
===============
从 README.md 的 timeline 中提取所有题目的历史分数，
采用与推荐脚本一致的 EMS 算法计算掌握度，
自动生成 PROGRESS.md 汇总表。

更新:
1. 历史分数过多时自动截断（仅保留最近 5 次）。
2. 掌握度算法统一为 EMS (EWMA + 历史债务)。
"""

import re
import datetime
import os
from collections import defaultdict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_PATH = os.path.join(PROJECT_ROOT, 'README.md')
PROGRESS_PATH = os.path.join(PROJECT_ROOT, 'PROGRESS.md')

# --- EMS 算法配置 (保持与 recommend.py 一致) ---
EWMA_ALPHA = 0.5
DEBT_SENSITIVITY = 0.5
DEBT_DECAY_RATE = 0.6


def calculate_ems(scores):
    """计算有效掌握度 (EMS)。"""
    if not scores:
        return 0.0

    # 1. EWMA (最近的表现权重更大)
    ewma = scores[0]
    for s in scores[1:]:
        ewma = EWMA_ALPHA * s + (1 - EWMA_ALPHA) * ewma

    # 2. 历史债务 (如果曾经跌落过分数，需要额外练习来偿还)
    worst = min(scores)
    if worst >= 3:
        return round(min(max(ewma, 1.0), 5.0), 2)

    # 找最后一次出现最低分的位置，计算之后的恢复次数
    worst_last_idx = max(i for i, s in enumerate(scores) if s == worst)
    recovery = len(scores) - 1 - worst_last_idx

    debt = max(0, 3 - worst) * DEBT_SENSITIVITY / (1 + recovery * DEBT_DECAY_RATE)
    ems = ewma - debt

    return round(min(max(ems, 1.0), 5.0), 2)


def parse_readme(file_path):
    """解析 README.md，支持 v4 单表格式和 v3.1 分日表格式。"""
    problems = defaultdict(lambda: {'name': '', 'difficulty': '', 'link': '', 'records': []})
    current_date = None
    current_year = datetime.date.today().year

    unified_pat = re.compile(
        r'\|\s+(\d{2}\.\d{2})\s+\|\s+\*\*(\d+)\.\s+(.*?)\*\*\s+\|\s+`(.*?)`\s+\|\s+(\d)\s+\|\s*(.*?)\s*\|'
    )
    table_pat = re.compile(
        r'\|\s+\*\*(\d+)\.\s+(.*?)\*\*\s+\|\s+`(.*?)`\s+\|\s+(\d)\s+\|'
    )
    date_pat = re.compile(r'^###\s+(\d{4}\.\d{2}\.\d{2})')
    link_pat = re.compile(r'\[LeetCode\]\((.*?)\)')

    if not os.path.exists(file_path):
        return problems

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            dm = date_pat.match(line)
            if dm:
                current_date = datetime.datetime.strptime(dm.group(1), '%Y.%m.%d').date()
                continue
            um = unified_pat.search(line)
            if um:
                date_str, pid_s, name, diff, score, time_str = um.groups()
                pid = int(pid_s)
                d = datetime.datetime.strptime(f"{current_year}.{date_str}", '%Y.%m.%d').date()
                problems[pid]['name'] = name.strip()
                problems[pid]['difficulty'] = diff
                time_in_seconds = None
                if time_str and 'LeetCode' not in time_str:
                    m_min = re.search(r'(\d+)分', time_str)
                    m_sec = re.search(r'(\d+)秒', time_str)
                    if m_min or m_sec:
                        mins = int(m_min.group(1)) if m_min else 0
                        secs = int(m_sec.group(1)) if m_sec else 0
                        time_in_seconds = mins * 60 + secs

                # 兼容新增的时间列，不影响现有复习逻辑
                problems[pid]['records'].append({'date': d, 'score': int(score), 'time': time_in_seconds})
                lm = link_pat.search(line)
                if lm: problems[pid]['link'] = lm.group(1)
                continue
            if current_date:
                tm = table_pat.search(line)
                if tm:
                    pid_s, name, diff, score = tm.groups()
                    pid = int(pid_s)
                    problems[pid]['name'] = name.strip()
                    problems[pid]['difficulty'] = diff
                    problems[pid]['records'].append({'date': current_date, 'score': int(score), 'time': None})
                    lm = link_pat.search(line)
                    if lm: problems[pid]['link'] = lm.group(1)
    return problems


def progress_bar(val, width=5):
    """将分值 (1~5) 转为圆形进度条。"""
    filled = round(val)
    filled = max(1, min(width, filled))
    return '●' * filled + '○' * (width - filled)


def generate_progress_md(problems):
    """生成 PROGRESS.md 内容。"""
    lines = ["# Progress\n", "> 此文件由 `scripts/update_progress.py` 自动生成，请勿手动编辑。\n\n"]

    total_problems = len(problems)
    total_attempts = sum(len(p['records']) for p in problems.values())
    all_scores = [r['score'] for p in problems.values() for r in p['records']]
    overall_avg = sum(all_scores) / len(all_scores) if all_scores else 0

    all_times = [r['time'] for p in problems.values() for r in p['records'] if r.get('time') is not None]
    overall_avg_s = sum(all_times) / len(all_times) if all_times else 0
    overall_time_str = f"{int(overall_avg_s // 60)}分{int(overall_avg_s % 60)}秒" if all_times else "-"

    lines.append(f"**总题数**: {total_problems}　|　"
                 f"**总练习次数**: {total_attempts}　|　"
                 f"**平均解题耗时**: {overall_time_str}　|　"
                 f"**整体平均分**: {overall_avg:.1f} {progress_bar(overall_avg)}\n\n")

    lines.append("| # | 题目 | 难度 | 次数 | 平均分 | 掌握度 | 平均耗时 | 上次日期 | 历史轨迹 |")
    lines.append("|--:|------|------|:----:|:------:|--------|----------|----------|----------|")

    for pid in sorted(problems.keys()):
        p = problems[pid]
        records = sorted(p['records'], key=lambda x: x['date'])
        scores = [r['score'] for r in records]
        avg = sum(scores) / len(scores)
        
        times = [r['time'] for r in records if r.get('time') is not None]
        avg_time_str = "-"
        if times:
            avg_s = sum(times) / len(times)
            avg_time_str = f"{int(avg_s // 60)}分{int(avg_s % 60)}秒"
            
        last_date = records[-1]['date'].strftime('%Y-%m-%d')
        
        # 历史轨迹截断
        MAX_HIST = 5
        if len(scores) > MAX_HIST:
            scores_str = f"({len(scores)}) .. " + ' → '.join(str(s) for s in scores[-MAX_HIST:])
        else:
            scores_str = ' → '.join(str(s) for s in scores)

        bar = progress_bar(avg)
        name = f"[{p['name']}]({p['link']})" if p['link'] else p['name']
        lines.append(
            f"| {pid} | {name} | `{p['difficulty']}` | "
            f"{len(records)} | {avg:.1f} | {bar} | {avg_time_str} | {last_date} | {scores_str} |"
        )

    lines.append(f"\n*Last updated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}*\n")
    return '\n'.join(lines)


if __name__ == "__main__":
    problems = parse_readme(README_PATH)
    if not problems:
        print("[WARN] No problems found in README.md")
        exit(1)

    # 1. 生成内容
    content = generate_progress_md(problems)

    # 2. 自动归档：保存到 progress/MMDD.md
    # 找到所有练习记录中的最后一天日期
    all_dates = []
    for p in problems.values():
        all_dates.extend([r['date'] for r in p['records']])
    
    if all_dates:
        last_practice_date = max(all_dates)
        mmdd = last_practice_date.strftime('%m%d')
        
        archive_dir = os.path.join(PROJECT_ROOT, 'progress')
        if not os.path.exists(archive_dir):
            os.makedirs(archive_dir)
            
        archive_path = os.path.join(archive_dir, f"{mmdd}.md")
        with open(archive_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        rel_archive = os.path.relpath(archive_path, PROJECT_ROOT)
        print(f"  [DONE] Progress report generated: {rel_archive}")
    else:
        print(f"  [WARN] No practice records found, no report generated.")
