#! -*- coding: utf-8 -*-
""" Coding Tools
"""

# Author: DengBoCong <bocongdeng@gmail.com>
#
# License: MIT License

import json
import re
import os
import sys
import logging
from datetime import datetime
from logging import Logger
from typing import Any

# 设定logging基础配置
LOGGING_FORMATTER = "%(asctime)s %(module)s [line:%(lineno)d] %(levelname)s: %(message)s"
logging.basicConfig(format=LOGGING_FORMATTER, datefmt="%Y-%m-%d %H:%M:%S")


class ProgressBar(object):
    """ 进度条工具 """

    EXECUTE = "%(current)d/%(total)d %(bar)s (%(percent)3d%%) %(metrics)s"
    DONE = "%(current)d/%(total)d %(bar)s - %(time).4fs/step %(metrics)s"

    def __init__(self,
                 total: int = 100,
                 num: int = 1,
                 width: int = 30,
                 fmt: str = EXECUTE,
                 symbol: str = "=",
                 remain: str = ".",
                 output=sys.stderr):
        """
        :param total: 执行总的次数
        :param num: 每执行一次任务数量级
        :param width: 进度条符号数量
        :param fmt: 进度条格式
        :param symbol: 进度条完成符号
        :param remain: 进度条未完成符号
        :param output: 错误输出
        """
        assert len(symbol) == 1
        self.args = {}
        self.metrics = ""
        self.total = total
        self.num = num
        self.width = width
        self.symbol = symbol
        self.remain = remain
        self.output = output
        self.fmt = re.sub(r"(?P<name>%\(.+?\))d", r"\g<name>%dd" % len(str(total)), fmt)

    def __call__(self, current: int, metrics: str):
        """
        :param current: 已执行次数
        :param metrics: 附加在进度条后的指标字符串
        """
        self.metrics = metrics
        percent = current / float(self.total)
        size = int(self.width * percent)
        bar = "[" + self.symbol * size + ">" + self.remain * (self.width - size - 1) + "]"

        self.args = {
            "total": self.total * self.num,
            "bar": bar,
            "current": current * self.num,
            "percent": percent * 100,
            "metrics": metrics
        }
        print("\r" + self.fmt % self.args, file=self.output, end="")

    def reset(self,
              total: int,
              num: int,
              width: int = 30,
              fmt: str = EXECUTE,
              symbol: str = "=",
              remain: str = ".",
              output=sys.stderr):
        """重置内部属性
        :param total: 执行总的次数
        :param num: 每执行一次任务数量级
        :param width: 进度条符号数量
        :param fmt: 进度条格式
        :param symbol: 进度条完成符号
        :param remain: 进度条未完成符号
        :param output: 错误输出
        """
        self.__init__(total=total, num=num, width=width, fmt=fmt,
                      symbol=symbol, remain=remain, output=output)

    def done(self, step_time: float, fmt=DONE):
        """
        :param step_time: 该时间步执行完所用时间
        :param fmt: 执行完成之后进度条格式
        """
        self.args["bar"] = "[" + self.symbol * self.width + "]"
        self.args["time"] = step_time
        # print("\r" + fmt % self.args + "\n", file=self.output, end="")
        return fmt % self.args


def get_dict_string(data: dict, prefix: str = "- ", precision: str = ": {:.4f} "):
    """将字典数据转换成key——value字符串
    :param data: 字典数据
    :param prefix: 组合前缀
    :param precision: key——value打印精度
    :return: 字符串
    """
    result = ""
    for key, value in data.items():
        result += (prefix + key + precision).format(value)

    return result


def get_logger(name: str,
               file_path: str,
               level: int = logging.INFO,
               mode: str = "a+",
               encoding: str = "utf-8",
               formatter: str = LOGGING_FORMATTER) -> Logger:
    """ 获取日志器
    :param name: 日志命名
    :param file_path: 日志文件存放路径
    :param level: 最低的日志级别
    :param mode: 读写日志文件模式
    :param encoding: 日志文件编码
    :param formatter: 日志格式
    :return: 日志器
    """
    if file_path and not file_path.endswith(".log"):
        raise ValueError("{} not a valid file path".format(file_path))

    if not os.path.exists(os.path.dirname(file_path)):
        os.mkdir(os.path.dirname(file_path))

    logger = logging.getLogger(name)
    logger.propagate = False
    logger.setLevel(level)

    if not logger.handlers:
        file_logger = logging.FileHandler(filename=file_path, mode=mode, encoding=encoding)
        file_logger.setLevel(logging.INFO)
        formatter = logging.Formatter(formatter)
        file_logger.setFormatter(formatter)
        logger.addHandler(file_logger)

    return logger


def save_model_config(key: str, model_desc: str, model_config: dict, config_path: str) -> bool:
    """ 保存单次训练执行时，模型的对应配置
    :param key: 配置key
    :param model_desc: 模型说明
    :param model_config: 训练配置
    :param config_path: 配置文件保存路径
    :return: 执行成功与否
    """
    try:
        config_json = {}
        if os.path.exists(config_path) and os.path.getsize(config_path) != 0:
            with open(config_path, "r", encoding="utf-8") as file:
                config_json = json.load(file)

        with open(config_path, "w+", encoding="utf-8") as config_file:
            model_config["execute_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            model_config["model_desc"] = model_desc
            config_json[key] = model_config
            json.dump(config_json, config_file, ensure_ascii=False, indent=4)

            return True
    except Exception:
        return False


def get_model_config(key: str, config_path: str) -> dict:
    """ 保存单次训练执行时，模型的对应配置
    :param key: 配置key
    :param config_path: 配置文件路径
    :return: 模型配置字典
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError("get_model_config: Not such file {}".format(config_path))

    try:
        with open(config_path, "r", encoding="utf-8") as file:
            return json.load(file).get(key, {})
    except Exception:
        return {}
