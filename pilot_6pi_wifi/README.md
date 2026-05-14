# pilot_6pi_wifi

这一层是给 6 台 Raspberry Pi 5 的 Wi-Fi-only 3Tx/3Rx CSI 拓扑准备的独立目录。

设计目标：
- 只做 Wi-Fi CSI，不接音频
- 3 个发射端分时发流量，3 个接收端持续监听
- 保留现有 pilot 的 raw-capture-first 思路，但把拓扑、命名、脚本和 runbook 收敛到 6 台 Pi 5
- 默认推荐 dedicated 5 GHz AP 和有线管理网，但也提供 dedicated 2.4 GHz 版本的完整 runbook，避免把 SSH 管理链路和 CSI 链路混在同一张无线网卡上

目录说明：
- configs/: 6 台 Pi 5 的设备角色、管理 IP、AP 配置模板
- scripts/: Tx TDMA、Rx CSI、主机端启动停止、拉回和验收脚本
- analysis/: CSI 预览脚本
- RUNBOOK_6PI_5GHZ_TDMA.md: 5 GHz 正式版本的完整执行手册
- RUNBOOK_6PI_24GHZ_TDMA.md: 2.4 GHz 版本的完整执行手册

最快启动顺序：
1. 先在 5 GHz 或 2.4 GHz runbook 里选一个目标频段，再按对应 RUNBOOK 完成 6 台 Pi 5 的 Bookworm 初始化、chrony、Nexmon 和 AP 设置。
2. 填写 configs/devices.yaml 里的 3 个 Tx MAC 地址。
3. 在控制主机执行 scripts/host_prepare_6pi.sh，把目录同步到全部节点。
4. 用 scripts/host_start_6pi_session.sh 启动一轮 3Tx/3Rx TDMA 会话。
5. 用 scripts/host_stop_6pi_session.sh 停止采集，再用 scripts/pull_session.sh 拉回数据。
6. 用 scripts/check_csi_rate.sh 和 analysis/parse_csi_preview.py 做快速质检。

建议：
- 5 GHz 版本先跑 36/20 的 bring-up profile，再切到 36/40 的 baseline profile
- 2.4 GHz 版本优先跑 11/20 的 bring-up profile，再根据扫描结果决定是否改到 1/20 或 6/20
