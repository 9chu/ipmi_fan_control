#!/bin/python3
# -*- coding: utf-8 -*-
import re
import time
import json
import logging
import argparse
import collections
import pyipmi
import pyipmi.interfaces
from pyipmi.sdr import SdrFullSensorRecord
from pydantic import BaseModel
from typing import List, Dict, Any
from prettytable import PrettyTable


class TemperatureThresholdConfig(BaseModel):
    sensor_regex: str
    temp_threshold: List[float]


class FanZoneConfig(BaseModel):
    enable: bool
    fan_list: List[str]
    temp_watch_list: List[TemperatureThresholdConfig]
    rpm_ratio: List[float]


class AppConfig(BaseModel):
    address: str
    port: int = 623
    username: str = "ADMIN"
    password: str
    interface_type: str = "lan"
    ipmb_address: int = 0x20
    trigger_interval: int = 5
    no_duplicated_set: bool = True
    cpu_fan_cfg: FanZoneConfig
    board_fan_cfg: FanZoneConfig


def dict_to_table(d):
    keys = list(d.keys())
    t = PrettyTable(keys)
    values = []
    for k in keys:
        values.append(d[k])
    t.add_row(values)
    return t


class IpmiFanControl:
    def __init__(self, config: AppConfig):
        self._config = config
        self._interface = pyipmi.interfaces.create_interface("ipmitool", interface_type=config.interface_type)
        self._connection = pyipmi.create_connection(self._interface)
        self._connection.session.set_session_type_rmcp(config.address, port=config.port)
        self._connection.session.set_auth_type_user(config.username, config.password)
        self._connection.target = pyipmi.Target(ipmb_address=config.ipmb_address)

        # 建立到 IPMI 的连接
        logging.info(f"Connecting to ipmi {config.address}:{config.port}")
        self._connection.session.establish()

        # 获取传感器列表
        logging.info(f"Reading sensor list")
        self._sensor_list = {}
        sdr_list = self._connection.get_device_sdr_list()
        for e in sdr_list:
            if isinstance(e, SdrFullSensorRecord):
                logging.info(f"Sensor {e.number}: {e.device_id_string}") # e.number 为传感器 ID
                self._sensor_list[e.device_id_string] = e

        self._sensor_reading_cache = {}

    def _fetch_sensor_readings(self, sensor_list: List[str]):
        ret = collections.OrderedDict()
        for name in sensor_list:
            if name not in self._sensor_list:
                logging.warning(f"Sensor {name} not found")
                continue
            sensor = self._sensor_list[name]
            try:
                if name in self._sensor_reading_cache:
                    reading = self._sensor_reading_cache[name]
                else:
                    reading = self._connection.get_sensor_reading(sensor.number)[0]
                    self._sensor_reading_cache[name] = reading
            except pyipmi.errors.CompletionCodeError as ex:
                if ex.cc == 0xCB:
                    reading = None
                else:
                    raise ex
            ret[name] = sensor.convert_sensor_raw_to_value(reading)
        return ret

    def _filter_sensor_by_regex(self, regex_expr: str):
        ret = []
        for name in self._sensor_list:
            groups = re.match(regex_expr, name, re.IGNORECASE)
            if not groups:
                continue
            ret.append(name)
        return ret

    def _evaluate_zone(self, zone_cfg: FanZoneConfig):
        # 如果规则关闭，则结束
        if not zone_cfg.enable:
            return None

        # 查询该区域风扇转速
        # fan_rpm_list = self._fetch_sensor_readings(zone_cfg.fan_list)
        # logging.debug(dict_to_table(fan_rpm_list))

        # 遍历规则，计算当前区域风扇的转速级别
        expected_rpm_level = None
        for e in zone_cfg.temp_watch_list:
            # 获取规则关联的传感器
            match_sensors = self._filter_sensor_by_regex(e.sensor_regex)
            if len(match_sensors) == 0:
                continue
            # 获取这些传感器的读数
            sensor_readings = self._fetch_sensor_readings(match_sensors)
            logging.debug(dict_to_table(sensor_readings))
            # 计算落到哪个区间
            for sensor_name in sensor_readings:
                sensor_level = 0
                sensor_level_threshold = 0
                sensor_reading = sensor_readings[sensor_name]
                for t in e.temp_threshold:
                    if t < sensor_reading:
                        sensor_level += 1
                        sensor_level_threshold = t
                    else:
                        break
                if expected_rpm_level is None or sensor_level > expected_rpm_level:
                    logging.debug(f"RPM level increased by sensor {sensor_name}, "
                                  f"with temperature {sensor_reading} > {sensor_level_threshold}")
                    expected_rpm_level = sensor_level

        # 没有传感器读数
        if expected_rpm_level is None:
            return None

        # 获取对应的转速
        i = 0
        target_ratio = zone_cfg.rpm_ratio[0]
        while expected_rpm_level != 0:
            i += 1
            expected_rpm_level -= 1
            if i >= len(zone_cfg.rpm_ratio):
                break
            target_ratio = zone_cfg.rpm_ratio[i]
        return target_ratio

    def _ipmi_set_fan_speed(self, zone_id: int, ratio_i: float):
        assert zone_id == 0x00 or zone_id == 0x01
        ratio = int(max(min(ratio_i, 100), 30))  # 保底转速 30%
        if ratio > ratio_i:
            logging.warning(f"Config fan speed too slow, adjust fan speed from {ratio_i} to {ratio}")
        self._connection.raw_command(0, 0x30, [0x70, 0x66, 0x01, zone_id, ratio])

    def run(self):
        try:
            last_cpu_zone_ratio = None
            last_board_zone_ratio = None
            while True:
                # 清空读数缓存
                self._sensor_reading_cache = {}

                # 计算各区域温度
                logging.debug(f"Evaluate CPU zone")
                ratio = self._evaluate_zone(self._config.cpu_fan_cfg)
                if ratio is not None:
                    if not self._config.no_duplicated_set or last_cpu_zone_ratio != ratio:
                        logging.info(f"CPU zone expected fan ratio: {ratio}%")
                        self._ipmi_set_fan_speed(0, ratio)
                        last_cpu_zone_ratio = ratio
                else:
                    last_cpu_zone_ratio = None

                logging.debug(f"Evaluate Board zone")
                ratio = self._evaluate_zone(self._config.board_fan_cfg)
                if ratio is not None:
                    if not self._config.no_duplicated_set or last_board_zone_ratio != ratio:
                        logging.info(f"Board zone expected fan ratio: {ratio}%")
                        self._ipmi_set_fan_speed(1, ratio)
                        last_board_zone_ratio = ratio
                else:
                    last_board_zone_ratio = None

                # 等待下次计算
                time.sleep(self._config.trigger_interval)
        except KeyboardInterrupt:
            logging.info(f"Received keyboard interrupt, exiting")
            return


def main():
    cmd_parser = argparse.ArgumentParser(prog="IPMI Fan Control")
    cmd_parser.add_argument("-c", "--config", type=str, required=True)
    cmd_args = cmd_parser.parse_args()

    # 加载配置文件
    logging.info(f"Reading configuration from {cmd_args.config}")
    with open(cmd_args.config, "r", encoding="utf-8") as f:
        config_json = json.load(f)

    # 启动控制器
    config = AppConfig(**config_json)
    fan_control = IpmiFanControl(config)
    fan_control.run()


def init_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger_format = logging.Formatter("[%(asctime)s][%(levelname)s][%(module)s:%(funcName)s:%(lineno)d] %(message)s")

    logger_output = logging.StreamHandler()
    logger_output.setLevel(logging.DEBUG)
    logger_output.setFormatter(logger_format)
    logger.addHandler(logger_output)


if __name__ == "__main__":
    init_logging()
    main()
