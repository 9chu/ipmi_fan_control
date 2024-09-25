# IPMI FAN CONTROL

适用于`H12DSI`的 IPMI 风扇转速控制器。

## 动机

由于超微主板没有提供风扇曲线调节的功能，在家用场景下使用猫扇等低转速风扇时主板无法给出合适的转速。

因此我们编写脚本，可以通过网络获取 BMC 传感器温度，并通过 IPMI 命令控制风扇转速按照设定调节。

## 使用

如果仅控制`FANA`、`FANB`，BMC 可以设置风扇控制为`Heavy I/O`。 如果连同 CPU 控制，需要设置为`Full Speed`。

创建配置文件，保存为`config.json`，通过命令行`-c config.json`启动脚本即可。

不提供守护进程，可以考虑使用`PM2`等进行管理。

参考配置：

```json5
{
  "address": "BMC IP 地址",
  "username": "ADMIN",  // 超微主板固定 ADMIN 用户名
  "password": "BMC 管理密码",
  "cpu_fan_cfg": {  // CPU 风扇控制（FAN1 ~ FAN6）
    "enable": false,  // CPU 风扇默认还是交给 BMC 管理，这里关闭
    "fan_list": ["FAN1", "FAN2", "FAN3", "FAN4", "FAN5", "FAN6"],  // 关联的风扇列表，无用
    // 温度监控列表
    "temp_watch_list": [
      {
        "sensor_regex": "CPU\\d Temp",  // 匹配监控的传感器名称，若匹配，则看对应传感器温度
        "temp_threshold": [40, 46, 52, 58]  // 温度阈值，当某个传感器温度超过阈值时，设定对应的挡位，例如超过 40 度，不超过 46 度，则为 1 档
      },
      {
        "sensor_regex": "CPU\\d_VRMIN Temp",
        "temp_threshold": [50, 55, 60, 65]
      }
    ],
    "rpm_ratio": [30, 45, 60, 75, 100]  // 风扇转速挡位，总是比 temp_threshold 多一档。第一个值为最低转速，第二个值为 1 档转速，以此类推
  },
  "board_fan_cfg": {  // 控制 FANA、FANB
    "enable": true,  // 开启主板风扇控制
    "fan_list": ["FANA", "FANB"],  // 关联的风扇列表，无用
    "temp_watch_list": [
      {
        "sensor_regex": "CPU\\d Temp",
        "temp_threshold": [40, 46, 52, 58]
      },
      {
        "sensor_regex": "CPU\\d_VRMIN Temp",
        "temp_threshold": [50, 55, 60, 65]
      },
      {
        "sensor_regex": "P\\d_VRM.+ Temp",
        "temp_threshold": [45, 50, 55, 60]
      },
      {
        "sensor_regex": "GPU\\d Temp",
        "temp_threshold": [40, 50, 60, 70]
      }
    ],
    "rpm_ratio": [50, 65, 80, 90, 100]
  }
}
```

## 声明

脚本仅供作者自用，未在其他类型主板进行测试，对于使用该脚本造成的任何问题（如烧毁器件等），作者概不负责。

## 参考

- https://zhuanlan.zhihu.com/p/393409078
