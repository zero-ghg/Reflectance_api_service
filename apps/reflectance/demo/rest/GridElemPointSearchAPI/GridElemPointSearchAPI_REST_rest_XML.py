# -*- coding: utf-8 -*-
'''
Created in 2016/03/28
@author: xjunior
'''
import sys
import time
import uuid
import webbrowser
from xml.etree import ElementTree as ET
# 看demo所在目录，添加路径
sys.path.append('../../..')
from demo.util import SignGenUtil

# 有些输出是中文字符，统一设置一下编码
# reload(sys)
# sys.setdefaultencoding('utf8')
'''
如：按起报时间、预报层次、预报时段、经纬度检索预报要素插值 getNafpEleAtPointByTimeAndLevelAndValidtimeRange
'''
if __name__ == '__main__':
    # 1. 调用方法的参数定义，并赋值
    # 1.1 接口url
    # 1.2 用户名&密码
    # 1.3 接口ID
    # 1.4 必选参数（按需加可选参数）
    #     资料：欧洲中心数值预报产品-低分辨率-全球
    #     时间
    #     起始预报时效
    #     终止预报时效
    #     经纬度点，北京（纬度39.8，经度116.4667）、上海（纬度31.2，经度121.4333）
    #     预报要素（单个)：气温
    #     预报层次（单个)：850hpa

    # 服务节点
    serviceNodeId = "NMIC_MUSIC_CMADAAS"
    # 接口服务端IP和端口
    serviceIp = "10.40.17.54:80"
    # 用户名&密码
    userId = 'NMIC_XTS_CMADAASTEST'
    pwd = 'test1234'
    # 序列化格式
    dataFormat = 'xml'
    # 接口url
    baseUrl = 'http://' + serviceIp + '/music-ws/api?\
serviceNodeId=' + serviceNodeId + '\
&userId=' + userId + '\
&interfaceId=getNafpEleAtPointByTimeAndLevelAndValidtimeRange\
&dataCode=NAFP_FOR_FTM_LOW_EC_GLB\
&time=20190601000000\
&minVT=0\
&maxVT=12\
&latLons=39.8/116.4667,31.2/121.4333\
&fcstEle=TEM\
&levelType=100\
&fcstLevel=850\
&dataFormat='
    # 接口url一次拼接
    baseUrl = baseUrl + dataFormat
    # 生成时间戳和uuid，并拼接接口url
    timestamp = str(int(round(time.time() * 1000)))
    nonce = str(uuid.uuid1())
    baseUrl += '&timestamp=' + timestamp
    baseUrl += '&nonce=' + nonce
    # 生成sign
    signParams = {'serviceNodeId': serviceNodeId,
                  'userId': "NMIC_XTS_CMADAASTEST",
                  'interfaceId': "getNafpEleAtPointByTimeAndLevelAndValidtimeRange",
                  'dataCode': "NAFP_FOR_FTM_LOW_EC_GLB",
                  'time': "20190601000000",
                  'minVT': "0",
                  'maxVT': '12',
                  'latLons': '39.8/116.4667,31.2/121.4333',
                  'fcstEle': 'TEM',
                  'levelType': '100',
                  'fcstLevel': '850',
                  'dataFormat': dataFormat,
                  'timestamp': timestamp,
                  'nonce': nonce,
                  'pwd': pwd
                  }
    signUtil = SignGenUtil.SignGenUtil()
    sign = signUtil.getSign(signParams)
    if (sign == ""):
        print("generate sign is None")
    # 拼接sign
    baseUrl+='&sign=' + sign
    # print(baseUrl)
    # 当前浏览器打开新标签
    webbrowser.open_new_tab(baseUrl)

