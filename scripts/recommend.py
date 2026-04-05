#!/usr/bin/env python3
"""
智能刷题复习推荐系统 v2.1
========================
采用多因子加权评分模型，为每道题目计算综合「紧迫度分数」，取 Top-N 推荐。
如果明天的 notebook 文件不存在，自动生成一份包含推荐题目的 ipynb。
"""

import re
import json
import math
import uuid
import datetime
import os
from collections import defaultdict

# --- 配置区 ---------------------------------------------------------------
FORGETTING_THRESHOLD_DAYS = 7   # 多少天后才触发"遗忘风险"
HOT_IRON_WINDOW_DAYS = 3        # "趁热打铁"窗口 (天)
NUM_RECOMMEND = 3               # 推荐题目数量

# 各维度权重
W_PASS_RATE   = 40   # 通过率权重 (最高优先级)
W_REVIEW_FREQ = 25   # 复习频次权重
W_FORGETTING  = 20   # 遗忘风险权重
W_DIFFICULTY  = 10   # 难度权重
W_HOT_IRON    = 15   # 趁热打铁奖励

DIFFICULTY_SCORE = {'Hard': 1.0, 'Medium': 0.6, 'Easy': 0.3}

# --- 项目路径 -------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_PATH = os.path.join(PROJECT_ROOT, 'README.md')
NOTEBOOK_DIR = os.path.join(PROJECT_ROOT, 'notebook')


# --- 解析 -----------------------------------------------------------------

def parse_readme(file_path):
    """解析 README.md，返回 {题号: [记录列表]} 的字典。"""
    history = defaultdict(list)
    current_date = None

    date_pattern = re.compile(r'^###\s+(\d{4}\.\d{2}\.\d{2})')
    item_pattern = re.compile(
        r'^\-\s+\*\*(\d+)\.\s+(.*?)\*\*\s+\|\s+`(.*?)`\s+\|\s+(.*?)\s+\|'
    )

    if not os.path.exists(file_path):
        print("[WARN] README.md not found")
        return history

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            dm = date_pattern.match(line)
            if dm:
                current_date = datetime.datetime.strptime(
                    dm.group(1), '%Y.%m.%d'
                ).date()
                continue

            im = item_pattern.match(line)
            if im and current_date:
                pid, name, difficulty, status = im.groups()
                needs_review = 'review' in status.lower()
                history[int(pid)].append({
                    'id': int(pid),
                    'name': name.strip(),
                    'difficulty': difficulty,
                    'status': status.strip(),
                    'needs_review': needs_review,
                    'date': current_date,
                })

    return history


# --- 评分引擎 -------------------------------------------------------------

def score_problem(records, today):
    """为单道题计算综合紧迫度分数 (0~100)，附带主要推荐原因。"""
    total = len(records)
    review_count = sum(1 for r in records if r['needs_review'])
    pass_count = total - review_count
    pass_rate = pass_count / total if total else 1.0
    last = records[-1]
    days_ago = (today - last['date']).days
    diff = last['difficulty']

    reasons = []

    # 1) 通过率维度
    s_pass = (1 - pass_rate) * W_PASS_RATE
    if pass_rate == 0:
        reasons.append(f"[!] 从未独立通过 (0/{total})，急需攻克")
    elif pass_rate < 0.5:
        reasons.append(f"[!] 通过率仅 {pass_count}/{total}，掌握薄弱")

    # 2) 复习频次维度
    s_review = min(math.log2(review_count + 1) / 3, 1.0) * W_REVIEW_FREQ
    if review_count >= 2:
        reasons.append(f"[R] 反复标记 Review 达 {review_count} 次")

    # 3) 遗忘风险维度
    if days_ago >= FORGETTING_THRESHOLD_DAYS:
        s_forget = min(math.log2(days_ago / FORGETTING_THRESHOLD_DAYS + 1), 1.0) * W_FORGETTING
        reasons.append(f"[T] 已有 {days_ago} 天未练习，记忆衰减风险高")
    else:
        s_forget = 0

    # 4) 难度维度
    s_diff = DIFFICULTY_SCORE.get(diff, 0.5) * W_DIFFICULTY

    # 5) 趁热打铁奖励
    if days_ago <= HOT_IRON_WINDOW_DAYS and last['needs_review']:
        s_hot = (1 - days_ago / (HOT_IRON_WINDOW_DAYS + 1)) * W_HOT_IRON
        reasons.append(f"[H] {days_ago} 天前刚做过且未通过，趁热打铁")
    else:
        s_hot = 0

    total_score = s_pass + s_review + s_forget + s_diff + s_hot

    # 已掌握且未过遗忘阈值 -> 大幅降权
    if pass_rate == 1.0 and review_count == 0 and days_ago < FORGETTING_THRESHOLD_DAYS:
        total_score *= 0.1
        reasons = ["[OK] 已完全掌握，暂无需复习"]

    primary_reason = reasons[0] if reasons else "常规复习"

    return total_score, primary_reason, {
        'pass_rate': s_pass,
        'review_freq': s_review,
        'forgetting': s_forget,
        'difficulty': s_diff,
        'hot_iron': s_hot,
    }


def recommend(history, num=NUM_RECOMMEND):
    """对所有题目评分并返回 Top-N 推荐列表。"""
    today = datetime.date.today()
    scored = []

    for pid, records in history.items():
        records.sort(key=lambda x: x['date'])
        score, reason, breakdown = score_problem(records, today)
        scored.append({
            'score': score,
            'reason': reason,
            'breakdown': breakdown,
            'record': records[-1],
            'total_times': len(records),
            'review_count': sum(1 for r in records if r['needs_review']),
            'pass_rate': sum(1 for r in records if not r['needs_review']) / len(records),
        })

    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:num], scored


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


def print_table(all_scored):
    W = 105
    print("\n" + "-" * W)
    print("  [Statistics] All Problems Overview")
    print("-" * W)
    header = (
        f"  {pad('ID', 6)} | {pad('Name', 24)} | "
        f"{pad('Count', 6)} | {pad('Pass Rate', 12)} | "
        f"{pad('Last Date', 12)} | {pad('Last Status', 24)} | Score"
    )
    print(header)
    print("-" * W)

    for item in sorted(all_scored, key=lambda x: x['record']['id']):
        r = item['record']
        name = truncate(r['name'], 22)
        pr = f"{int(item['pass_rate']*100)}%"
        pr_detail = f"{item['total_times'] - item['review_count']}/{item['total_times']} ({pr})"
        status = truncate(r['status'], 22)
        score_str = f"{item['score']:.1f}"

        print(
            f"  {pad(r['id'], 6)} | {pad(name, 24)} | "
            f"{pad(item['total_times'], 6)} | {pad(pr_detail, 12)} | "
            f"{pad(r['date'].strftime('%Y-%m-%d'), 12)} | {pad(status, 24)} | {score_str}"
        )

    print("-" * W)


def print_recommendations(recs):
    W = 105
    print()
    print("-" * W)
    print("  [Recommend] Today's Review Plan (Multi-Factor Weighted Scoring)")
    print("-" * W)

    if not recs:
        print("  No review recommendations. Keep exploring new problems!")
        print("-" * W)
        return

    for idx, rec in enumerate(recs, 1):
        r = rec['record']
        bd = rec['breakdown']
        print(f"  [{idx}] {r['id']}. {r['name']}  ({r['difficulty']})")
        print(f"      Reason : {rec['reason']}")
        print(f"      Score  : {rec['score']:.1f}  "
              f"( pass={bd['pass_rate']:.1f}  review={bd['review_freq']:.1f}"
              f"  forget={bd['forgetting']:.1f}  diff={bd['difficulty']:.1f}"
              f"  hot={bd['hot_iron']:.1f} )")
        if idx < len(recs):
            print()

    print("-" * W)
    print(f"  Config: pass_rate={W_PASS_RATE} | review_freq={W_REVIEW_FREQ}"
          f" | forgetting={W_FORGETTING} | difficulty={W_DIFFICULTY}"
          f" | hot_iron={W_HOT_IRON}")
    print(f"  Thresholds: forgetting >= {FORGETTING_THRESHOLD_DAYS}d"
          f" | hot_iron <= {HOT_IRON_WINDOW_DAYS}d")
    print("-" * W)


# --- Notebook 自动生成 ----------------------------------------------------

def generate_notebook(recs, target_date):
    """
    根据推荐结果，自动生成明天的 ipynb 文件。
    文件路径: notebook/<year>/code_<MMDD>.ipynb
    """
    year_str = target_date.strftime('%Y')
    mmdd_str = target_date.strftime('%m%d')
    dir_path = os.path.join(NOTEBOOK_DIR, year_str)
    file_path = os.path.join(dir_path, f'code_{mmdd_str}.ipynb')

    if os.path.exists(file_path):
        print(f"\n  [INFO] Notebook already exists: {os.path.relpath(file_path, PROJECT_ROOT)}")
        return file_path

    os.makedirs(dir_path, exist_ok=True)

    date_display = target_date.strftime('%Y-%m-%d')
    cells = []

    # Cell 0: Header
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

    # Cell 1: Review section marker
    cells.append({
        "cell_type": "markdown",
        "id": str(uuid.uuid4()),
        "metadata": {},
        "source": [
            "# Review"
        ]
    })

    # Generate one code cell per recommended problem
    for rec in recs:
        r = rec['record']
        cells.append({
            "cell_type": "code",
            "execution_count": None,
            "id": str(uuid.uuid4()),
            "metadata": {},
            "outputs": [],
            "source": [
                f"# {r['id']}. {r['name']}\n",
                f"# {r['difficulty'][0]}\n",
                "# \n",
            ]
        })

    # Cell: New problems section marker
    cells.append({
        "cell_type": "markdown",
        "id": str(uuid.uuid4()),
        "metadata": {},
        "source": [
            "# New"
        ]
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
    print(f"\n  [CREATED] {rel}")
    print(f"  Today's notebook generated with {len(recs)} review problems.")
    return file_path


# --- 入口 -----------------------------------------------------------------

if __name__ == "__main__":
    history = parse_readme(README_PATH)
    recs, all_scored = recommend(history, NUM_RECOMMEND)

    print_table(all_scored)
    print_recommendations(recs)

    # 自动生成当天的 notebook (如果不存在)
    today = datetime.date.today()
    if recs:
        generate_notebook(recs, today)
