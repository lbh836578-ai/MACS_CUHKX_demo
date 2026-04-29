# CUHK-Y WitMotion WT9011DCL-BT50 IMU 简易操作手册（含最小 BLE 扩展）

> 版本：v1.0
> 最近修订：2026-04-20
> 适用对象：已经拿到 WitMotion WT9011DCL-BT50，只想最快验证姿态数据、改好基础参数，并把 IMU 并到当前 CUHK-Y CSI/Audio 实验里的人

---

## 0. 先看你当前这类设备的结论

WT9011DCL-BT50 在工程上最重要的 5 件事：

1. 它对外是 `BLE 5.0` 设备，但协议层仍然是 Wit 自家的**二进制寄存器协议**：
   - 模块上报数据包通常以 `0x55` 开头
   - 主机下发命令通常以 `0xFF 0xAA` 开头
2. 它默认持续上报的是 `0x55 0x61` 包，也就是：
   - `3 轴加速度`
   - `3 轴角速度`
   - `3 轴欧拉角`
3. `磁场 / 四元数 / 温度 / 电量` 这类内容，很多时候**不是默认持续推流**，而是要靠读寄存器命令触发返回
4. 官方页面给出的默认回传率是 `10 Hz`，最高 `200 Hz`
5. 对你当前这套多模态系统，**最稳的做法不是把 IMU 先绑到跑 Nexmon 的那台 Pi 上**，而是先用：
   - 手机 App 做验机
   - Windows 官方软件做参数确认
   - Mac / Linux / 独立树莓派 + Python 做正式 BLE 采集

一句话判断：

- **临时验证**：先用手机或 Windows，把 1 只 IMU 在 `10 Hz` 或 `50 Hz` 跑通
- **正式实验**：用独立 BLE 主机采 1 到 2 只 IMU，统一到 `50 Hz`，每只传感器单独落 CSV，并和 CSI / Audio 一起拍手同步

---

## 1. 最推荐的三种用法

### 方案 A：手机 App 临时验机

适合你刚拿到 IMU，只想确认：

- 设备能开机
- 蓝牙能被扫到
- 加速度 / 角速度 / 姿态角会实时变化
- 磁场校准流程能正常走完

优点：

- 最快
- 不需要写代码
- 最容易排除“设备坏了 / 没电 / 根本没广播”这类低级问题

缺点：

- 不适合正式数据归档
- 多设备管理麻烦
- 很难和你当前的 `pilot/` 目录规范直接对齐

### 方案 B：Windows 官方软件做参数和校准

适合你要做下面这些动作：

- 把默认回传率从 `10 Hz` 调到 `50 Hz`
- 做加速度校准和磁场校准
- 读版本号、电量、寄存器
- 用官方上位机先确认这只传感器状态正常

优点：

- 对设备参数控制最直接
- 读写寄存器比手机 App 更清楚
- 最适合做“出厂状态检查”

缺点：

- 依赖 Windows
- 不是你后续正式多模态采集的最终主机

### 方案 C：Linux / Python 正式采集

适合正式实验。

推荐顺序：

1. 先按官方 Python BLE 示例连通 1 只设备
2. 再把回调改成写 CSV
3. 最后才考虑多 IMU 并发采集

优点：

- 最容易并入你现在的 `pilot/` 和离线分析流程
- 文件命名、会话编号、拍手同步都好统一
- 最方便和 CSI / Audio 一起做后处理

缺点：

- BLE 并发和断连问题需要自己兜底
- 不能像 `tcpdump` / `arecord` 那样天然“一个命令就完”

---

## 2. 开始前的最小前提

默认你已经满足下面这些最低条件：

- 你手上的型号确实是 `WT9011DCL-BT50`
- 你知道它**不是** `WT901SDCL-BT50`
- 至少有 1 台可用的 BLE 主机：
  - iPhone / Android 手机
  - Windows 笔记本
  - Mac / Linux / Raspberry Pi + BLE 适配器
- 你已经给每一只 IMU 贴好物理标签，例如：
  - `imu01_left_wrist`
  - `imu02_right_wrist`
  - `imu03_waist`
- 你准备好一个统一的会话编号，例如 `demo01`
- 你不会让同一只 IMU 同时被：
  - 手机 App
  - Windows 官方软件
  - Python 采集脚本
  同时抢连接

这里还有一个非常关键的工程点：

- **不要把 IMU 正式采集主机优先放到正在跑 CSI 的那台树莓派上**
- 对你现在这套系统，BLE 主机优先级建议是：
  1. 控制电脑 / Mac
  2. 独立 Windows / Linux 笔记本
  3. 独立 Raspberry Pi + USB 蓝牙适配器
  4. 最后才考虑和 Nexmon CSI 共机

原因很简单：

- `wlan0` 做 Nexmon CSI 时，本来就已经是高风险链路
- 树莓派板载 Wi-Fi / Bluetooth 共用射频资源时，会增加排障复杂度
- 你现在最不需要的是把 CSI 问题和 BLE 问题缠在一起

---

## 3. 方案 A：手机 App 下的最小验机步骤

这一节只做最短闭环：

- 让手机扫到 WT9011DCL-BT50
- 连上后看到实时姿态数据
- 做一次磁场校准
- 确认这只 IMU 不是“有广播但数据不动”的死设备

### 3.1 安装官方 App

官方入口现在是：

- Android：Google Play 里搜 `witmotion`
- iPhone：App Store 里的 `WitMotion`

先装好 App，再给它这些权限：

- 蓝牙
- 定位
- 后台蓝牙扫描权限（如果系统弹窗要求）

> Android 上如果不给定位权限，很多 BLE App 会出现“蓝牙明明开着，但就是扫不到设备”的假故障。

### 3.2 上电并扫描设备

先确认传感器已经供电并开始广播，然后在 App 里扫描。

你通常应该看到类似这种名字：

- `WT...`
- `WT901...`

如果一只设备一直扫不到，先不要急着写代码，先排这 4 个最常见原因：

1. 这只传感器电量太低
2. 它已经被另一台手机 / 电脑连住了
3. 你当前手机蓝牙权限没开全
4. 周围 BLE 设备太多，列表被淹了

### 3.3 连上以后先看这几项

连上以后，你最先应该确认下面 4 组数据会随着手动转动传感器发生变化：

1. `AccX / AccY / AccZ`
2. `GyroX / GyroY / GyroZ`
3. `AngleX / AngleY / AngleZ`
4. 电量或版本信息页能正常读取

如果你把传感器平放、翻转、旋转，`AngleX / Y / Z` 一直完全不变，那就不要继续往下跑正式采集了，先把验机问题解决。

### 3.4 先做一次磁场校准

官方 BLE 9 轴传感器最需要注意的不是加速度本身，而是**航向角和磁场融合**。

最短校准动作：

1. 在 App 里找到磁场校准入口
2. 开始校准
3. 让传感器分别绕 `X / Y / Z` 三个轴各转 `2 - 3` 圈
4. 结束校准
5. 远离笔记本壳体、桌腿、移动电源、排插、磁吸支架以后，再看 `AngleZ`

> 如果你在强磁干扰环境里做校准，后面 `Heading / Yaw` 漂掉不是算法问题，而是校准本身就脏了。

### 3.5 手机验机阶段的最短验收标准

你至少要同时满足下面 4 条，才说明这只 IMU 值得进入下一阶段：

1. App 能稳定扫到设备
2. 连接后 `Acc / Gyro / Angle` 会实时变化
3. 磁场校准能正常开始和结束
4. 连续转动 `30 s` 时没有马上断连

---

## 4. 方案 B：Windows 官方软件下的参数确认与校准

这一节的目的不是正式采集，而是把设备基础状态统一掉。

### 4.1 下载官方 Windows 软件

官方入口现在是：

- `WITMOTION PC Software`
- 官方下载中心里对应的 `WitMotion.exe`

这一步的意义只有一个：

- 让你在一台更适合“看寄存器、看参数、改速率”的主机上，把传感器状态先定下来

### 4.2 Windows 上最先确认什么

连上设备以后，先确认：

1. 能扫到 `WT...` 设备
2. 连接后实时数据正常刷新
3. 能读到版本号
4. 能读到电量
5. 能做加速度校准和磁场校准

### 4.3 推荐的第一版参数

对你当前这类人体动作 / 多模态实验，最稳的首版参数不是 `200 Hz`，而是下面这组：

- **Smoke test**：`10 Hz`
- **正式 baseline**：`50 Hz`
- **只在单设备短时测试时才考虑**：`100 Hz`
- **不要作为第一轮默认值**：`200 Hz`

原因很务实：

1. `10 Hz` 足够判断链路通不通
2. `50 Hz` 对人体动作和同步预实验已经够用
3. `100 / 200 Hz` 会明显提高 BLE 丢包、断连、主机处理压力和多设备冲突概率

Wit 官方 BLE 5.0 协议里的回传率索引可以直接记这几个：

| 目标速率 | 协议值 |
|----------|--------|
| `10 Hz` | `0x06` |
| `20 Hz` | `0x07` |
| `50 Hz` | `0x08` |
| `100 Hz` | `0x09` |
| `200 Hz` | `0x0A` |

### 4.4 必做的两类校准

#### 加速度校准

适用场景：

- 刚到手的新设备
- 明显感觉静止时加速度零偏很怪
- 装配或贴装方式变过

#### 磁场校准

适用场景：

- 你想认真用 `Yaw / Heading`
- 你会记录转身、朝向、躯干姿态
- 你后面要把欧拉角和 CSI / Audio 事件一起对齐

最短建议：

- **只要换了实验环境，就把磁场校准至少重做一次**

### 4.5 Windows 阶段要避免什么

这一步先不要干 3 件事：

1. 不要一上来同时连很多只传感器
2. 不要同时把手机 App 也开着
3. 不要边改速率边怀疑 Python 脚本有 bug

Windows 这一步的目标只是把设备状态统一掉，不是证明你的正式采集程序没问题。

---

## 5. 方案 C：Linux / Python 下的最小采集闭环

这一节是整个文档最核心的部分。

目标只有一个：

- 在你自己的主机上，把 WT9011DCL-BT50 的数据稳定写成文件

### 5.1 先理解 BLE 5.0 协议到底返回什么

Wit 官方 BLE 5.0 文档里，最值得你记住的规则只有这几条：

1. 默认上报包是 `0x55 0x61`
2. `0x61` 这 20 字节里默认带的是：
   - `AccX/Y/Z`
   - `GyroX/Y/Z`
   - `AngleX/Y/Z`
3. 读寄存器命令格式是：

```text
FF AA 27 <REG> 00
```

4. 模块对这些寄存器的返回是 `0x55 0x71`
5. 常用补充读取命令是：

```text
读磁场:     FF AA 27 3A 00
读四元数:   FF AA 27 51 00
读温度:     FF AA 27 40 00
读电量:     FF AA 27 64 00
```

6. 常用写命令是：

```text
解锁寄存器:     FF AA 69 88 B5
加速度校准:     FF AA 01 01 00
开始磁场校准:   FF AA 01 07 00
结束磁场校准:   FF AA 01 00 00
保存配置:       FF AA 00 00 00
设置回传率:     FF AA 03 <RATE> 00
```

也就是说：

- **IMU 不是“只连上就自动给你所有字段”**
- 正式记录时，你通常要么：
  - 只记默认的 `Acc / Gyro / Angle`
  - 要么在后台周期性补读 `Mag / Quaternion / Temp / Power`

### 5.2 先用官方 Python SDK 跑通 1 只设备

官方 GitHub 仓库里已经有 Python BLE 示例，不需要你从零开始猜 GATT 逻辑。

```bash
cd ~
git clone https://github.com/WITMOTION/WitBluetooth_BWT901BLE5_0.git
cd WitBluetooth_BWT901BLE5_0/Python/BWT901BLE5.0_python_sdk

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install bleak

python test.py
```

这个官方示例的基本逻辑是：

1. 用 `bleak` 扫描 BLE 设备
2. 过滤名称里带 `WT` 的设备
3. 让你输入要连接的 MAC
4. 连上以后在回调里打印 `deviceData`

> 官方 Python 示例默认是**单设备思路**，也就是一次选 1 只设备连通。对你现在的预实验，这反而是好事，因为它最容易先把链路跑稳。

### 5.3 Linux / Python 侧最重要的 UUID 认知

官方 Python 示例里，BLE 服务和特征一般是这组：

```text
Service UUID: 0000ffe5-0000-1000-8000-00805f9a34fb
Notify UUID:  0000ffe4-0000-1000-8000-00805f9a34fb
Write UUID:   0000ffe9-0000-1000-8000-00805f9a34fb
```

但你需要知道一个现实问题：

- Wit 官方仓库里还有一套较老的 Android 示例，里面出现过另一组 `49535343-...` 的 UUID
- 所以**不要在你自己的脚本里同时硬编码两套 UUID 然后瞎试**
- 对 `WT9011DCL-BT50`，优先以官方 Python 示例能跑通的那套为准
- 如果你自己的设备服务发现结果和示例不一致，再去看当前固件的实际 GATT 表

最短排障方式：

```bash
python - <<'PY'
import asyncio
from bleak import BleakScanner, BleakClient

TARGET_MAC = "把这里换成你的 MAC"

async def main():
    device = await BleakScanner.find_device_by_address(TARGET_MAC, timeout=20)
    if device is None:
        print("device not found")
        return
    async with BleakClient(device, timeout=15) as client:
        for service in client.services:
            print("SERVICE", service.uuid)
            for ch in service.characteristics:
                print("  CHAR", ch.uuid, ch.properties)

asyncio.run(main())
PY
```

### 5.4 正式记录时怎么改官方 Python 示例

官方 `test.py` 默认只是打印 `deviceData`。你正式实验至少要改 2 件事：

1. 给每只 IMU 明确一个逻辑标签
2. 把回调改成写 CSV，而不是只打印

最小改法可以是把 `updateData()` 改成这种思路：

```python
from pathlib import Path
import csv
import time

OUT = Path("demo01_imu01_left_wrist.csv")
writer = None
csv_file = None

def updateData(device):
    global writer, csv_file

    if writer is None:
        csv_file = OUT.open("w", newline="")
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[
                "host_ts",
                "device_name",
                "acc_x", "acc_y", "acc_z",
                "gyro_x", "gyro_y", "gyro_z",
                "angle_x", "angle_y", "angle_z",
                "hx", "hy", "hz",
                "q0", "q1", "q2", "q3",
                "temp_c",
                "power_percent",
            ],
        )
        writer.writeheader()

    writer.writerow({
        "host_ts": time.time(),
        "device_name": device.deviceName,
        "acc_x": device.get("AccX"),
        "acc_y": device.get("AccY"),
        "acc_z": device.get("AccZ"),
        "gyro_x": device.get("AsX"),
        "gyro_y": device.get("AsY"),
        "gyro_z": device.get("AsZ"),
        "angle_x": device.get("AngX"),
        "angle_y": device.get("AngY"),
        "angle_z": device.get("AngZ"),
        "hx": device.get("HX"),
        "hy": device.get("HY"),
        "hz": device.get("HZ"),
        "q0": device.get("Q0"),
        "q1": device.get("Q1"),
        "q2": device.get("Q2"),
        "q3": device.get("Q3"),
        "temp_c": device.get("T"),
        "power_percent": device.get("PowerPercent"),
    })
    csv_file.flush()
```

这里有 2 个注意点：

1. 官方不同语言示例里的角度 key 命名有 `AngleX` / `AngX` 两类写法，**你要以你手上那份 Python 示例里的实际 key 为准**
2. `HX / HY / HZ / Q0 / Q1 / Q2 / Q3 / T / PowerPercent` 这类值，只有在脚本后台有主动补读相应寄存器时才会稳定出现

### 5.5 什么时候不要一上来多设备并发

官方产品页提到“蓝牙 multi-link adapter 最多 4 台”，但这不等于：

- 你手上任意一台笔记本内置蓝牙都能稳采 4 只 IMU
- 你随便一个 `asyncio gather` 就能无脑稳定

对你现在的预实验，最稳的策略是：

1. **先 1 只设备单独跑通**
2. 再尝试 `2 只`
3. 只有单机 `2 只` 稳定 `30 s - 60 s` 没明显掉包 / 断连，才考虑更多

如果你后面真的要多只 IMU 并发，推荐顺序是：

1. 1 只 IMU = 1 个独立 Python 进程
2. 每只 IMU 1 个独立 CSV
3. 主机端统一会话编号和开始时间
4. 不要先追求“所有 IMU 写进一个超级脚本”

---

## 6. 在当前 quickstart 拓扑上挂最小 IMU 扩展

这一节回答的是下面这个实际场景：

- `pi2`：CSI Tx
- `pi3`：CSI Rx + 环境麦
- `pi5`：个人麦节点
- `WT9011DCL-BT50`：参与者佩戴的 IMU

这里最容易搞错的一点是：

- **IMU 不是 Tx / Rx 节点**
- 它是参与者身上的独立终端
- 真正的“主机”是那个负责扫 BLE、连 BLE、写 CSV 的控制端

### 6.1 最稳的角色分配

按你现在这套系统，最稳的第一版角色应该是：

| 节点 | 实际角色 | 挂什么设备 | 为什么这样分 |
|------|----------|------------|--------------|
| `pi2` | CSI Tx | `eth0` 管理网线 + 自带 `wlan0` | 只负责发 Wi-Fi 帧，不叠加 IMU 任务 |
| `pi3` | CSI Rx + 环境音频 | `eth0` + `wlan0` + ReSpeaker | 这里已经够忙，不建议第一轮再叠 BLE IMU 主机 |
| `pi5` | 个人麦节点 | `eth0` + USB 声卡 + 领夹麦 | 继续只做近端语音 ground truth |
| `cuhky-host` / 控制电脑 | **IMU BLE 采集主机** | Mac / Linux / Windows + BLE 适配器 | 最适合统一命名、写 CSV、同步多模态时间轴 |
| `imu01...imuNN` | 参与者 IMU | WT9011DCL-BT50 | 真正佩戴在人体上，用来提供局部运动参考 |

最务实的策略是：

- **先把 IMU 主机放在控制电脑上**
- 不要第一天就把 IMU 采集也塞给 `pi3`

### 6.2 佩戴和坐标一致性比算法更重要

如果你后面想拿 IMU 去给 CSI 做动作对照，真正会毁掉数据的通常不是模型，而是**佩戴方向不一致**。

最短规则：

1. 每只传感器固定一个部位
2. 每个部位固定一种贴装方向
3. 每场实验都不要临时换方向
4. 第一次佩戴完成后，拍照记录方向

一个可执行的例子是：

- `imu01_left_wrist`：左手手背，排针朝手肘
- `imu02_right_wrist`：右手手背，排针朝手肘
- `imu03_waist`：腰前正中，排针朝上

只要这个方向在每次实验里一致，后面你再决定是：

- 直接用原始坐标
- 做重映射
- 只看模长

都会轻松得多。

### 6.3 同房间版本怎么挂 IMU

如果你现在只是做**同房间版本**的 quickstart 扩展，可以先按下面这套摆：

```text
房间 A（同房间版本）

    pi2 (CSI Tx)  ---------------------->  pi3 (CSI Rx + ReSpeaker)

                [参与者 A]      [参与者 B]
                 |      \      /      |
                 |       \____/       |
           imu01(left wrist)   imu02(right wrist)

    pi5 (USB声卡 + 2个领夹麦)
    cuhky-host / 笔记本 (BLE host for WT9011DCL-BT50)
```

这一版最小系统里：

- `pi2 -> pi3` 还是主 CSI 链路
- `pi3` 还是主要环境麦节点
- `pi5` 还是个人麦节点
- `IMU` 只是额外加在参与者身上，提供局部运动参考
- `BLE host` 最好还是控制电脑

### 6.4 穿墙版本怎么理解 IMU

如果你后面做穿墙版本：

- IMU 仍然跟人走，不跟房间走
- CSI 看的是无线传播变化
- Audio 看的是声场
- IMU 看的是**佩戴点本地运动**

也就是说，IMU 更像 ground truth，不是环境传感器。

---

## 7. 标准启动顺序

对你现在这套 `CSI + Audio + IMU` 最小系统，推荐启动顺序是：

1. 确认每只 WT9011DCL-BT50 电量正常
2. 在手机或 Windows 上确认所有 IMU 已完成基本校准
3. 在 BLE 主机上启动 IMU 采集脚本，但先不开始动作
4. 让参与者佩戴好 IMU 并静止 `5 s`
5. 启动 `pi2` 的 CSI 发流量
6. 启动 `pi3` 的 CSI Rx
7. 启动 `pi3` 的环境麦录音
8. 启动 `pi5` 的个人麦录音
9. 所有人就位后拍手一次
10. 开始动作或说话任务

这里的逻辑是：

- IMU 比较容易先起来
- CSI 和 Audio 才是你现在更脆弱的链路
- 拍手仍然是整个多模态对齐里最便宜、最有效的细同步标记

---

## 8. 最小验证 demo 路线

如果你想只做一条最短闭环，不要一上来多只 IMU。先做下面这条：

1. 只拿 `1` 只 WT9011DCL-BT50
2. 在 Windows 上把它设成 `50 Hz`
3. 在 Mac / Linux 上跑官方 Python 示例
4. 转动、摆臂、静止各 `10 s`
5. 输出 `1` 个 CSV
6. 用 Excel / Python 看 `Acc / Gyro / Angle` 是否有明显阶段差异

如果这条都不稳定，不要继续加第二只。

---

## 9. 最短验收标准

只看下面 5 条就够了：

1. 手机或 Windows 能稳定扫到 WT9011DCL-BT50
2. 至少 1 只 IMU 在 `50 Hz` 下能持续 `30 s` 不断连
3. Python 侧能把实时数据写成 `CSV`
4. 拍手或快速挥手时，`Acc / Gyro / Angle` 都有明显突变
5. 和 CSI / Audio 同时运行时，没有因为 IMU 主机而把主链路搞崩

只要这 5 条满足，就说明你的 WT9011DCL-BT50 已经不是“玩具连通”，而是进入了可用于预实验的状态。

---

## 10. 高频错误和最短处理

### 10.1 手机上一直扫不到设备

先排这 4 个：

1. 设备没电
2. 设备已经被别的主机连住
3. 手机没开蓝牙 / 定位权限
4. 你在系统蓝牙页里看到了设备，但 App 还没获得扫描权限

### 10.2 Python 一直 `No devices found`

先分开看：

1. 你是不是把设备名字过滤得太死，只允许 `WT9011DCL-BT50`
2. 实际广告名可能只带 `WT`
3. 设备不一定一直持续广播，重启电源后再扫一轮
4. 主机蓝牙适配器本身可能不稳定

### 10.3 连上就断，或者 `100 / 200 Hz` 特别不稳

这通常不是 `bleak` 自己坏了，而是：

1. 回传率太高
2. 多设备并发太早
3. 主机蓝牙适配器太弱
4. 脚本里读寄存器太频繁

最短处理顺序：

1. 先退回 `50 Hz`
2. 只留 1 只设备
3. 先只记默认 `0x61` 包
4. 最后才加 `磁场 / 四元数 / 温度 / 电量` 补读

### 10.4 CSV 里只有 `Acc / Gyro / Angle`，没有磁场或四元数

这通常不是设备坏了，而是你只收了默认 `0x61` 包。

最短处理：

- 记得后台周期性发：
  - `FF AA 27 3A 00`
  - `FF AA 27 51 00`
  - `FF AA 27 40 00`
  - `FF AA 27 64 00`

### 10.5 `AngleZ / Heading` 漂得很离谱

先不要急着怪算法，优先排：

1. 没做磁场校准
2. 校准时旁边有金属或电源干扰
3. 实验现场和校准现场不是同一环境
4. 你把传感器贴在了强磁干扰源附近

### 10.6 左右手数据看起来完全反了

这通常不是“模型错了”，而是：

1. 两只 IMU 贴装方向不一致
2. 你没记录每只 IMU 的朝向
3. 你把欧拉角当成全局真值了

最短处理：

- 先固定贴装方向
- 再做统一标定动作
- 最后才谈算法对齐

### 10.7 想把 IMU 直接挂到跑 Nexmon 的 Pi 上

可以，但不建议作为第一轮。

因为你很难第一时间分清：

- 是 BLE 主机有问题
- 还是 CSI 让无线链路变差
- 还是树莓派板载蓝牙 / Wi-Fi 共存带来的副作用

最短处理：

- 先把 IMU BLE 主机放到控制电脑
- 等 IMU 本身跑稳以后，再考虑共机

### 10.8 官方仓库里看到两套 UUID，脚本该信谁

最务实的策略是：

1. 先跟官方 Python 示例一致
2. 如果连不上，再打印本机实际 GATT 服务表
3. 不要同时硬编码两套 UUID 在脚本里瞎撞

### 10.9 多只 IMU 同时跑时文件命名开始混乱

最短规则：

1. 1 只 IMU = 1 个固定逻辑标签
2. 1 只 IMU = 1 个独立 CSV
3. 文件名里一定带：
   - `session`
   - `body part`
   - `device label`

例如：

```text
demo01_imu01_left_wrist.csv
demo01_imu02_right_wrist.csv
demo01_imu03_waist.csv
```

---

## 11. 当前这套环境下一句话建议

你现在最应该做的不是先追 `200 Hz` 或多设备并发，而是：

1. 先用手机或 Windows 把 `WT9011DCL-BT50` 的 `50 Hz + 校准` 跑通
2. 再在控制电脑上用官方 Python BLE 示例连通 `1` 只设备
3. 把输出落成 `1` 个结构化 CSV
4. 最后才把 IMU 并到你当前的 `CSI + Audio` quickstart 里做拍手同步