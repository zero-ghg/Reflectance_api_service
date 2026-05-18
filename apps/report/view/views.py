import logging
from datetime import datetime
from pathlib import Path

from django.conf import settings
from rest_framework.response import Response
from rest_framework.views import APIView

from report.generate_report.generate_qwen_report import QwenReportComponent
from report.generate_report.weather_data import WeatherDataComponent

logger = logging.getLogger(__name__)


class Generate_report(APIView):
    def post(self, request):
        report_type = request.data.get("type")
        if report_type is None:  # 检查参数是否存在
            return Response({"code": 400, "msg": "缺少参数 type", })

        # 检查类型是否为整数
        if not isinstance(report_type, int):
            return Response({"code": 400, "msg": "参数 type 须为整数"})

        # 检查值是否有效（非负）
        if report_type < 0:
            return Response({"code": 400, "msg": "参数 type 不能为负数"})

        try:
            if report_type != 0:  # 目前只支持类型0
                return Response({"code": 400, "msg": f"暂不支持的报告类型", })

            out_dir = Path(settings.MEDIA_ROOT) / "report"  # 报告输出目录
            out_dir.mkdir(parents=True, exist_ok=True)  # 创建目录（如果不存在）
            ts = datetime.now().strftime("%Y%m%d%H%M%S")  # 生成时间戳
            weather_path = out_dir / f"tianjin_weather_{ts}.json"  # 天气数据文件路径
            risk_path = out_dir / f"tianjin_risk_{ts}.json"  # 风险分析文件路径
            docx_path = out_dir / f"weather_report_{ts}.docx"  # Word报告文件路径

            weather_comp = WeatherDataComponent()  # 创建天气数据组件
            all_weather = weather_comp.get_all_districts_weather(days=3, hourly=True)  # 获取天津各区3天逐小时天气
            if not all_weather:  # 如果获取失败
                return Response({"code": 400, "msg": "未能获取天气数据", })

            risk_summary = weather_comp.analyze_weather_risks(all_weather)  # 分析天气风险
            weather_comp.save_weather_data(
                all_weather, risk_summary, str(weather_path), str(risk_path)
            )  # 保存天气数据和风险分析到JSON文件

            report_comp = QwenReportComponent()  # 创建报告生成组件
            report_comp.run(str(weather_path), str(risk_path), str(docx_path))  # 生成Word报告

            media_url = settings.MEDIA_URL  # 获取媒体文件URL前缀
            if not str(media_url).endswith("/"):  # 确保URL以/结尾
                media_url = f"{media_url}/"
            file_url = f"{media_url}report/{docx_path.name}"  # 构建报告文件的完整URL

            # 从请求中获取当前服务的主机地址
            host = request.get_host()  # 获取主机地址（如 127.0.0.1:8000）
            scheme = request.scheme  # 获取协议（http 或 https）
            full_url = f"{scheme}://{host}{file_url}"  # 构建完整的文件访问URL

            resp_time = risk_summary.get(  # 获取响应时间
                "timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
            return Response(
                {
                    "code": 200,  # 成功状态码
                    "msg": "胜场报告成功",  # 成功消息
                    "data": {
                        "type": report_type,  # 报告类型
                        "url": full_url,  # 报告文件URL
                        "time": resp_time,  # 数据时间
                    },
                }
            )
        except ImportError as exc:  # 捕获导入错误
            return Response(
                {"code": 500, "msg": str(exc)}
            )
        except FileNotFoundError as exc:  # 捕获文件未找到错误
            return Response(
                {"code": 400, "msg": str(exc)}
            )
        except Exception:  # 捕获其他所有异常
            logger.exception("生成天气报告失败")  # 记录异常日志
            return Response(
                {"code": 500,"msg": "生成报告失败，请稍后重试"})
