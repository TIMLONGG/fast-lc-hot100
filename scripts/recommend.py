#!/usr/bin/env python3
"""
智能刷题复习推荐系统 v4.0
========================
基于 1-5 掌握度分数 + EMS(有效掌握度) + 间隔复习 的推荐引擎。

评分标尺:
  5 = 秒杀    4 = 顺畅    3 = 通过    2 = 艰难    1 = 未通过

核心算法:
  1. EMS (Effective Mastery Score): EWMA + 历史债务衰减
  2. 间隔复习: 基于 EMS 动态计算复习间隔
  3. 紧迫度: overdue_ratio * difficulty_weight * (6 - EMS) * frequency_factor
  4. 练习次数衰减: 防止做过多次的题霸占推荐位
"""

import re
import json
import math
import uuid
import datetime
import os
from collections import defaultdict

# --- 配置区 ---------------------------------------------------------------
NUM_RECOMMEND = 3
EWMA_ALPHA = 0.5          # 指数加权移动平均的衰减系数
DEBT_SENSITIVITY = 0.5    # 历史债务的灵敏度
DEBT_DECAY_RATE = 0.6     # 历史债务的衰减速率 (v4: 0.4→0.6，更快恢复)
REPEAT_DAMPEN = 0.4       # 练习次数衰减系数，每多练一次紧迫度降低一些

DIFFICULTY_WEIGHT = {'Hard': 1.5, 'Medium': 1.2, 'Easy': 1.0}

# EMS -> 建议复习间隔 (天)
INTERVAL_MAP = [
    (1.5, 1),
    (2.5, 3),
    (3.5, 5),
    (4.5, 10),
    (5.1, 14),
]

# --- 项目路径 -------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_PATH = os.path.join(PROJECT_ROOT, 'README.md')
NOTEBOOK_DIR = os.path.join(PROJECT_ROOT, 'notebook')


# --- 解析 README ----------------------------------------------------------

def parse_readme(file_path):
    """
    解析 README.md，返回 {题号: [记录列表]}。
    支持: 单表格式(v4, 日期列) / 分日表格式(v3.1) / S:N列表(v3.0)
    """
    history = defaultdict(list)
    current_date = None
    current_year = datetime.date.today().year

    # v5 格式: | 04.14 | **98. 验证二叉搜索树** | `Medium` | 3 | 7分59秒 | 中序遍历解法薄弱 | [LeetCode](...) |
    # 兼容 5/6/7 列: 分数后面可能跟 时间、备注、链接 的任意组合
    unified_pat = re.compile(
        r'\|\s+(\d{2}\.\d{2})\s+\|\s+\*\*(\d+)\.\s+(.*?)\*\*\s+\|\s+`(.*?)`\s+\|\s+(\d)\s+\|'
    )
    # v3.1 分日表格行: | **42. 接雨水** | `Hard` | 3 | [LeetCode](...) |
    table_pat = re.compile(
        r'\|\s+\*\*(\d+)\.\s+(.*?)\*\*\s+\|\s+`(.*?)`\s+\|\s+(\d)\s+\|'
    )
    # 分日表格日期头: ### 2026.04.04
    date_pat = re.compile(r'^###\s+(\d{4}\.\d{2}\.\d{2})')
    # 时间格式
    time_pat = re.compile(r'\d+分\d+秒')
    # 链接格式
    link_pat = re.compile(r'\[LeetCode\]')

    if not os.path.exists(file_path):
        print("[WARN] README.md not found")
        return history

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()

            # 检查分日格式的日期头
            dm = date_pat.match(line)
            if dm:
                current_date = datetime.datetime.strptime(
                    dm.group(1), '%Y.%m.%d'
                ).date()
                continue

            # v4/v5 单表格式
            um = unified_pat.search(line)
            if um:
                date_str, pid, name, diff, score = um.groups()
                d = datetime.datetime.strptime(
                    f"{current_year}.{date_str}", '%Y.%m.%d'
                ).date()

                # 从分数之后的所有列中提取 时间、备注
                # 将分数后面的部分按 | 分割
                rest = line[um.end():]
                cols = [c.strip() for c in rest.split('|') if c.strip()]

                time_val = ""
                note_val = ""
                for col in cols:
                    if time_pat.search(col):
                        time_val = col
                    elif link_pat.search(col):
                        pass  # 跳过链接列
                    else:
                        note_val = col

                history[int(pid)].append({
                    'id': int(pid),
                    'name': name.strip(),
                    'difficulty': diff,
                    'score': int(score),
                    'time': time_val,
                    'note': note_val,
                    'date': d,
                })
                continue

            # v3.1 分日表格行 (需要 current_date)
            if current_date:
                tm = table_pat.search(line)
                if tm:
                    pid, name, diff, score = tm.groups()
                    history[int(pid)].append({
                        'id': int(pid),
                        'name': name.strip(),
                        'difficulty': diff,
                        'score': int(score),
                        'date': current_date,
                    })

    return history


def _migrate_old_status(status):
    """将旧的 Pass/Review 状态映射为 1-5 分数。"""
    s = status.lower()
    if 'review' in s:
        if '做不出来' in status or '完全' in status:
            return 1
        if 'pass' in s:
            return 3
        return 2
    if 'pass' in s:
        if '(r)' in s or '(R)' in s.lower():
            return 3
        # 有备注说明过程中有些曲折
        if '(' in status:
            return 4
        return 5
    return 3  # fallback


# --- EMS 计算 -------------------------------------------------------------

def calculate_ems(scores):
    """
    计算 Effective Mastery Score。

    1. EWMA: 近期分数权重更大
    2. 历史债务: 如果最低分 < 3，产生持久惩罚，随后续练习次数衰减
    3. EMS = clamp(EWMA - debt, 1.0, 5.0)
    """
    if not scores:
        return 3.0

    # EWMA
    ewma = scores[0]
    for s in scores[1:]:
        ewma = EWMA_ALPHA * s + (1 - EWMA_ALPHA) * ewma

    # 历史债务
    worst = min(scores)
    if worst >= 3:
        return round(min(max(ewma, 1.0), 5.0), 2)

    # 找最后一次出现最低分的位置，计算之后的恢复次数
    worst_last_idx = max(i for i, s in enumerate(scores) if s == worst)
    recovery = len(scores) - 1 - worst_last_idx

    debt = max(0, 3 - worst) * DEBT_SENSITIVITY / (1 + recovery * DEBT_DECAY_RATE)
    ems = ewma - debt

    return round(min(max(ems, 1.0), 5.0), 2)


def get_review_interval(ems):
    """基于 EMS 计算建议复习间隔 (天)。"""
    for threshold, days in INTERVAL_MAP:
        if ems <= threshold:
            return days
    return 14


# --- 紧迫度排序 -----------------------------------------------------------

def compute_urgency(history):
    """为每道题计算紧迫度，返回排序后的列表。"""
    today = datetime.date.today()
    results = []

    for pid, records in history.items():
        records.sort(key=lambda x: x['date'])
        scores = [r['score'] for r in records]
        last = records[-1]

        ems = calculate_ems(scores)
        interval = get_review_interval(ems)
        days_ago = (today - last['date']).days
        overdue_ratio = days_ago / interval if interval > 0 else 0
        diff_w = DIFFICULTY_WEIGHT.get(last['difficulty'], 1.0)

        # v4: 练习次数衰减因子，做过越多次紧迫度越低
        freq_factor = 1.0 / (1 + REPEAT_DAMPEN * max(0, len(records) - 1))
        urgency = overdue_ratio * diff_w * (6 - ems) * freq_factor

        results.append({
            'id': pid,
            'name': last['name'],
            'difficulty': last['difficulty'],
            'total_times': len(records),
            'scores': scores,
            'ems': ems,
            'interval': interval,
            'days_ago': days_ago,
            'overdue': overdue_ratio,
            'freq_factor': round(freq_factor, 2),
            'urgency': round(urgency, 2),
            'last_date': last['date'],
            'last_score': last['score'],
            'last_note': last.get('note', ''),
        })

    results.sort(key=lambda x: x['urgency'], reverse=True)
    return results


# --- 终端打印 -------------------------------------------------------------

def calc_len(s):
    return sum(2 if ord(c) > 127 else 1 for c in str(s))

def pad(s, width):
    s = str(s)
    return s + " " * max(0, width - calc_len(s))

def truncate(s, max_width):
    current = 0
    for i, c in enumerate(s):
        w = 2 if ord(c) > 127 else 1
        if current + w > max_width - 3:
            return s[:i] + "..."
        current += w
    return s


def print_table(results):
    W = 115
    print("\n" + "-" * W)
    print("  [统计] 所有题目概览")
    print("-" * W)
    header = (
        f"  {pad('ID', 6)} | {pad('题目名称', 22)} | "
        f"{pad('难度', 8)} | {pad('次数', 6)} | "
        f"{pad('分数序列', 14)} | {pad('掌握度', 8)} | "
        f"{pad('复习间隔', 10)} | {pad('上次练习', 10)} | 紧迫度"
    )
    print(header)
    print("-" * W)

    for item in sorted(results, key=lambda x: x['id']):
        name = truncate(item['name'], 20)
        scores_str = ','.join(str(s) for s in item['scores'])
        if len(scores_str) > 12:
            scores_str = scores_str[:10] + ".."
        interval_str = f"{item['interval']}天"
        days_str = f"{item['days_ago']}天前"

        print(
            f"  {pad(item['id'], 6)} | {pad(name, 22)} | "
            f"{pad(item['difficulty'], 8)} | {pad(item['total_times'], 6)} | "
            f"{pad(scores_str, 14)} | {pad(item['ems'], 8)} | "
            f"{pad(interval_str, 10)} | {pad(days_str, 10)} | {item['urgency']}"
        )

    print("-" * W)


def print_recommendations(results, num):
    W = 115
    recs = results[:num]

    print()
    print("-" * W)
    print("  [推荐] 今日复习计划")
    print("-" * W)

    if not recs:
        print("  当前没有建议复习的题目，去刷点新题吧！")
        print("-" * W)
        return recs

    for idx, r in enumerate(recs, 1):
        scores_str = ' -> '.join(str(s) for s in r['scores'])
        overdue_label = "已过期" if r['overdue'] > 1.0 else "进行中"
        print(f"  [{idx}] {r['id']}. {r['name']}  ({r['difficulty']})")
        print(f"      掌握度: {r['ems']} | 复习间隔: {r['interval']}天 | "
              f"上次练习: {r['days_ago']}天前 | 状态: {overdue_label}")
        print(f"      历史轨迹: [{scores_str}] | 紧迫度: {r['urgency']}")
        if r['last_note']:
            print(f"      备注: {r['last_note']}")
        if idx < len(recs):
            print()

    print("-" * W)
    print(f"  评分说明: 5=秒杀 4=顺畅 3=通过 2=艰难 1=未通过")
    print(f"  公式: 掌握度 = EWMA + 历史债务 | 紧迫度 = 过期比例 * 难度权重 * (6 - 掌握度) * 次数衰减")
    print("-" * W)

    return recs


# --- Notebook 自动生成 ----------------------------------------------------

def generate_notebook(recs, target_date):
    """
    根据推荐结果，自动生成当天的 ipynb 文件。
    路径: notebook/<year>/code_<MMDD>.ipynb
    """
    year_str = target_date.strftime('%Y')
    mmdd_str = target_date.strftime('%m%d')
    dir_path = os.path.join(NOTEBOOK_DIR, year_str)
    file_path = os.path.join(dir_path, f'code_{mmdd_str}.ipynb')

    if os.path.exists(file_path):
        print(f"\n  [提示] Notebook 已存在: "
              f"{os.path.relpath(file_path, PROJECT_ROOT)}")
        return file_path

    os.makedirs(dir_path, exist_ok=True)

    date_display = target_date.strftime('%Y-%m-%d')
    cells = []

    # Header cell
    cells.append({
        "cell_type": "code",
        "execution_count": None,
        "id": str(uuid.uuid4()),
        "metadata": {},
        "outputs": [],
        "source": [
            "# fast hot100\n",
            f"# {date_display}"
        ]
    })

    # Review section
    cells.append({
        "cell_type": "markdown",
        "id": str(uuid.uuid4()),
        "metadata": {},
        "source": ["# Review"]
    })

    for r in recs:
        diff_letter = r['difficulty'][0]
        source = [
            f"# {r['id']}. {r['name']}\n",
            f"# {diff_letter}\n",
            "# \n",
        ]
        if r.get('last_note'):
            source.append(f"# 上次备注: {r['last_note']}\n")

        cells.append({
            "cell_type": "code",
            "execution_count": None,
            "id": str(uuid.uuid4()),
            "metadata": {},
            "outputs": [],
            "source": source
        })

    # New section
    cells.append({
        "cell_type": "markdown",
        "id": str(uuid.uuid4()),
        "metadata": {},
        "source": ["# New"]
    })

    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3 (ipykernel)",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "codemirror_mode": {"name": "ipython", "version": 3},
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "nbconvert_exporter": "python",
                "pygments_lexer": "ipython3",
                "version": "3.10.18"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 5
    }

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(notebook, f, ensure_ascii=False, indent=1)

    rel = os.path.relpath(file_path, PROJECT_ROOT)
    print(f"\n  [已创建] {rel}")
    print(f"  已生成包含 {len(recs)} 道复习题的 Notebook。")
    return file_path

# --- 入口 -----------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LeetCode 智能复习推荐系统 v3.0")
    parser.add_argument('-n', type=int, default=NUM_RECOMMEND,
                        help=f"推荐题目数量 (默认: {NUM_RECOMMEND})")
    args = parser.parse_args()

    history = parse_readme(README_PATH)
    results = compute_urgency(history)

    print_table(results)
    recs = print_recommendations(results, args.n)

    # 自动生成当天的 notebook (如果不存在)
    today = datetime.date.today()
    folder = os.path.join(PROJECT_ROOT, "notebook", str(today.year))
    filename = f"code_{today.strftime('%m%d')}.ipynb"
    file_path = os.path.join(folder, filename)

    if recs and not os.path.exists(file_path):
        generate_notebook(recs, today)
    elif os.path.exists(file_path):
        print(f"\n  [跳过] Notebook 已存在，未覆盖: {os.path.relpath(file_path, PROJECT_ROOT)}")
