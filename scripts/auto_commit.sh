#!/bin/bash

# 获取当前日期，格式为 20xx-xx-xx (YYYY-MM-DD)
CURRENT_DATE=$(date +"%Y-%m-%d")

DRY_RUN=0
if [ "$1" == "--dry-run" ] || [ "$1" == "-d" ]; then
    DRY_RUN=1
    echo "========= 模拟运行模式 (DRY RUN) ========="
fi

echo "开始自动提交代码..."
echo "当前日期: $CURRENT_DATE"

if [ $DRY_RUN -eq 1 ]; then
    echo "将要执行的命令如下："
    echo "----------------------------------------"
    echo "$ git add ."
    echo "$ git commit -m \"add $CURRENT_DATE code\""
    echo "$ git push"
    echo "----------------------------------------"
    echo "模拟完成，未执行任何实际操作。"
else
    # 实际执行 Git 流程
    git add .
    git commit -m "add $CURRENT_DATE code"
    git push
    echo "代码提交与推送完成！"
fi
