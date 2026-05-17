# coding=utf-8
"""
MUSIC 连通性测试。

默认：雷达文件列表 getRadaFileByTimeRange（与气象大数据云平台「接口调用测试」一致）。

在 demo 目录执行：
  python test_music_sta_elem.py

运行前请确认 client.config 中 music_server / music_port 与网页可访问地址一致。
勿将真实密码提交到公共 git，本地写死仅作联调。
"""
from __future__ import annotations

import sys
from pathlib import Path

# ----- 本地联调写死（不用环境变量）-----
MUSIC_USER_ID = "BETJ_FLZX_LI_YUN_BO"
MUSIC_PASSWORD = "Zhfymqm672!@$"  # 在此填写 API 密码
# True：测站点要素 getSurfEleByTime；False：测雷达文件列表

MUSIC_TEST_INTERFACE_ID = "getRadaFileByTimeRange"

_SRC_ROOT = Path(__file__).resolve().parent.parent
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from cma.music.DataQueryClient import DataQueryClient


def main() -> None:
    demo_dir = Path(__file__).resolve().parent
    config_file = demo_dir / "client.config"
    if not config_file.is_file():
        print("未找到 client.config:", config_file)
        sys.exit(1)

    if not MUSIC_PASSWORD:
        print("请在本文件顶部将 MUSIC_PASSWORD 写为你的 API 密码。")
        sys.exit(1)

    client = DataQueryClient(configFile=str(config_file))
    userId = MUSIC_USER_ID
    pwd = MUSIC_PASSWORD

    interfaceId = MUSIC_TEST_INTERFACE_ID
    params = {
        "dataCode": "RADA_L3_MST_CREF_QC",
        "timerange": "[20260513000000,20260513010000]",
        "dataFormat": "json",
        "tdspath": "true",
        "limitCnt": "10",
    }
    ret = client.callAPI_to_fileList(userId, pwd, interfaceId, params)

    print("errorCode:", ret.request.errorCode)
    print("errorMessage:", ret.request.errorMessage)
    print("fileCount(request.rowCount):", getattr(ret.request, "rowCount", ""))
    if ret.request.errorCode != 0:
        print("接口返回失败，请根据 errorMessage 检查 params / 白名单 / music_server。")
        return

    print("fileInfos count:", len(ret.fileInfos))
    for i, fi in enumerate(ret.fileInfos[:5]):
        print(f"  [{i}] {fi.fileName} size={fi.size} url={fi.fileUrl!r}")


if __name__ == "__main__":
    main()
