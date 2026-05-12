# pilot

这一层用于把 CUHK-Y-wifi_audio.md 里的手工命令收敛成可重复执行的控制脚本、分析脚本和元数据模板。

当前这套脚本已经按“raw capture only”收缩：

- 不依赖 `experiment_plan.csv`
- 不强依赖 `sessions.csv` 或 `clap_timestamps.csv`
- 采集时只依赖命令行里的 `--session`、`--channel`、`--duration`、`--card` 等参数
- 脚本职责只包括：开始录制、结束录制、把 raw data 写到本机目录、再由控制主机回收

当前默认部署范围与 CUHK-Y-wifi_audio.md v1.2 保持一致：

- 单房间 4 台 Pi
- 不包含 ESP32 和穿墙链路
- rpi-csi-rx-a 与 rpi-csi-rx-b 是同房间双接收点
- rpi-lav-audio 负责个人麦 ground truth

当前目录结构：

- analysis/: CSI、音频预览和同步脚本
- configs/: 设备和网络配置记录模板
- data/: 原始数据和处理结果
- logs/: 运行日志和 pid 文件
- metadata/: 可选的会话、拍手对齐和设备备注模板
- scripts/: 采集和数据回传脚本

建议用法：

1. 先补齐 configs/ 下的占位信息，尤其是 devices.yaml 和 router.yaml。
2. 在各台 RPi 上创建同名目录，并把 scripts/ 分发过去。
3. 先在 rpi-csi-rx-a 跑通最小链路，再把同样的 CSI + ReSpeaker 路径复制到 rpi-csi-rx-b。
4. 用 tmux 或 systemd-run 启动长时间采集脚本。
5. `scripts/start_audio_env.sh` 默认按 ReSpeaker 2-Mics Pi HAT v2 的 2 通道录音。
6. `scripts/start_audio_lav.sh` 既支持 1 块双输入 USB 声卡，也支持 2 块单输入 USB 声卡并行录制成 `*_lavA.wav` 和 `*_lavB.wav`。
7. 每轮采集结束后立刻运行 analysis/ 下的预览脚本做快速质检。
8. 用 scripts/pull_session.sh 拉回会话数据；metadata/ 只在你想补人工标注时再更新。

raw data 默认落点：

- 各采集 Pi 本机：`pilot/data/raw/`
- 控制主机回收后：`pilot/data/pulls/<session>/`

最低依赖：

- CSI 采集：nexutil、tcpdump、makecsiparams
- 音频采集：arecord、soxi（可选）
- 回传：ssh、rsync、shasum
- Python 分析：numpy、matplotlib，以及按脚本需要安装 nexcsi、soundfile、pyannote.audio