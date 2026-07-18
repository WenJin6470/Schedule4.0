"""
╔══════════════════════════════════════════════════════════════════════════╗
║           📅 电子课表系统 —— main.py（程序入口 + 连接器）                 ║
║                     （前后端分离架构 · 中间层）                            ║
╚══════════════════════════════════════════════════════════════════════════╝

📌 本文件的角色
═══════════════════════════════════════════════════════════════════════════
main.py 是整个程序的入口，也是前后端分离架构中的"中间层"。

它的唯一工作就是"牵线搭桥"——把前端（schedule_frontend.py）的信号和
后端（schedule_backend.py）的方法一对一连接起来。就像一个"媒人"，
负责介绍双方认识。

三层架构回顾：
  ┌──────────────────┐     信号（Signal）     ┌──────────┐
  │schedule_frontend │ ───────────────────→  │ main.py  │
  │    （前端）       │                       │（连接器）  │
  │                  │ ←───────────────────  │          │
  └──────────────────┘   调用公开方法（Method） └──────────┘
                                                     │
                                               调用后端方法
                                                     │
                                               ┌─────▼──────────┐
                                               │schedule_backend │
                                               │   （后端）       │
                                               └────────────────┘

📌 运行方式
═══════════════════════════════════════════════════════════════════════════
  # 在虚拟环境中运行：
  venv\\Scripts\\python main.py

  # 或者直接双击 run_separated.bat
"""

import logging
import os
import sys
from datetime import datetime

from PySide6.QtWidgets import QApplication

# ================================================================
# ★ 导入前端窗口和后端逻辑 ★
# ================================================================
# 前端窗口（负责界面显示）
from schedule_frontend import ScheduleClassroomFrontend

# 后端逻辑（负责时间管理和窗口辅助操作）
from schedule_backend import TimeManager, WindowHelper


# ================================================================
#  主函数：创建窗口、创建后端、连接信号
# ================================================================
def main() -> None:
    """
    程序入口函数。
    ------------
    执行顺序：
      1. 创建 QApplication（PySide6 应用程序对象，必须有）
      2. 配置日志系统（log 目录 + 当天日志文件 + 终端输出）
      3. 创建前端窗口实例
      4. 创建后端实例
      5. 把前端的信号和后端的方法连接起来（核心步骤！）
      6. 显示窗口
      7. 启动事件循环（app.exec()）
    """
    # ================================================================
    #  第1步：配置日志系统
    #  - 创建 log/ 目录（如果不存在）
    #  - 日志文件按天命名：schedule_2026-07-18.log
    #  - 同时输出到终端（StreamHandler）和文件（FileHandler）
    # ================================================================
    script_dir: str = os.path.dirname(os.path.abspath(__file__))
    log_dir: str = os.path.join(script_dir, 'log')
    os.makedirs(log_dir, exist_ok=True)

    log_filename: str = f"schedule_{datetime.now().strftime('%Y-%m-%d')}.log"
    log_filepath: str = os.path.join(log_dir, log_filename)

    # 配置根日志记录器 —— 所有子 logger 都会继承此配置
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)-7s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_filepath, encoding='utf-8'),   # 写入当天日志文件
            logging.StreamHandler(sys.stdout),                      # 同时输出到终端
        ]
    )

    logger: logging.Logger = logging.getLogger('main')
    logger.info(f"日志系统已就绪，日志文件：{log_filepath}")

    # 第2步：创建 PySide6 应用程序对象
    # QApplication 是所有 PySide6 程序的"发动机"，必须最先创建
    logger.info("正在创建 QApplication...")
    app: QApplication = QApplication(sys.argv)
    logger.info("QApplication 创建成功")

    # 第3步：创建前端窗口
    logger.info("正在创建前端窗口（ScheduleClassroomFrontend）...")
    window: ScheduleClassroomFrontend = ScheduleClassroomFrontend(language='Chinese', theme='lightcolor')
    logger.info("前端窗口创建完成")

    # 第4步：创建后端实例
    logger.info("正在创建后端实例（TimeManager + WindowHelper）...")
    time_manager: TimeManager = TimeManager()      # 时间管理器：负责获取实时时间
    window_helper: WindowHelper = WindowHelper()    # 窗口辅助器：负责关闭窗口等操作
    logger.info("后端实例创建完成")

    # ================================================================
    # 第5步：★ 连接信号和槽 —— 前后端分离的关键步骤！★
    #
    # 连接1：定时器时间更新 → 前端时间标签
    #   TimeManager 每秒触发回调 → 调用前端的 update_time_display() 更新时间显示
    #
    # 连接2：关闭按钮点击 → 关闭所有窗口并退出
    #   前端发射 close_requested 信号 → 调用 WindowHelper.close_all() 关闭窗口
    # ================================================================

    # ----- 连接1：定时器 → 更新时间显示 -----
    # TimeManager 启动时传入回调函数，每秒将当前时间推送给前端的 update_time_display()
    logger.info("正在连接信号：定时器 → 前端时间显示")
    time_manager.start(lambda time_str: window.update_time_display(time_str))
    logger.info("定时器已启动，时间显示信号已连接")

    # ----- 连接2：关闭按钮 → 关闭所有窗口 -----
    # 用户点击 × 按钮 → 前端发射 close_requested 信号 → 关闭所有窗口并退出
    logger.info("正在连接信号：关闭按钮 → 退出程序")
    window.close_requested.connect(
        lambda: window_helper.close_all(
            [window.get_time_window(), window.get_root_window()],
            app
        )
    )
    logger.info("关闭按钮信号已连接")

    # 第6步：显示时间窗口
    logger.info("正在显示时间窗口...")
    window.show()
    logger.info("时间窗口已显示，进入事件循环")

    # 第7步：启动事件循环
    # app.exec() 会进入"等待状态"，不停地监听用户的操作
    # 直到 WindowHelper.close_all() 调用 app.quit()，exec() 才返回，程序退出。
    # sys.exit() 确保程序退出时返回正确的退出码。
    exit_code: int = app.exec()
    logger.info(f"事件循环已退出（exit_code={exit_code}），程序结束")
    sys.exit(exit_code)


# ================================================================
#  程序入口
# ================================================================
if __name__ == "__main__":
    main()
