# -*- coding: utf-8 -*-
'''
Created in 2016/03/28
@author: xjunior
'''
import sys
import time
import uuid
import webbrowser
# 看demo所在目录，添加路径
sys.path.append('../../..')
from demo.util import SignGenUtil

# 有些输出是中文字符，统一设置一下编码
# reload(sys)
# sys.setdefaultencoding('utf8')
'''
如：按时间检索地面数据要素 getSurfEleByTime
'''
if __name__ == '__main__':
    # 1. 调用方法的参数定义，并赋值
    # 1.1 接口url
    # 1.2 用户名&密码
    # 1.3 接口ID
    # 1.4 必选参数（按需加可选参数）
    #     资料：中国地面逐小时
    #     检索要素：站号、站名、小时降水、气压、相对湿度、能见度、2分钟平均风速、2分钟风向
    #     检索时间
    #     排序：按照站号从小到大

    # 服务节点
    serviceNodeId = 'NMIC_MUSIC_CMADAAS'
    # 接口服务端IP和端口
    serviceIp = '10.40.17.54:80'
    # 用户名&密码
    userId = 'NMIC_XTS_CMADAASTEST'
    pwd = 'test1234'
    # 序列化格式
    dataFormat = 'text'
    # 接口url
    baseUrl = 'http://' + serviceIp + '/music-ws/api?\
serviceNodeId=' + serviceNodeId + '\
&userId=' + userId + '\
&interfaceId=getSurfEleByTime\
&dataCode=SURF_CHN_MUL_HOR\
&elements=Station_ID_C,PRE_1h,PRS,RHU,VIS,WIN_S_Avg_2mi,WIN_D_Avg_2mi,Q_PRS\
&times=20190601000000\
&orderby=Station_ID_C:ASC\
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
                  'userId': 'NMIC_XTS_CMADAASTEST',
                  'interfaceId': 'getSurfEleByTime',
                  'dataCode': 'SURF_CHN_MUL_HOR',
                  'elements': 'Station_ID_C,PRE_1h,PRS,RHU,VIS,WIN_S_Avg_2mi,WIN_D_Avg_2mi,Q_PRS',
                  'times': '20190601000000',
                  'orderby': 'Station_ID_C:ASC',
                  'dataFormat': dataFormat,
                  'timestamp': timestamp,
                  'nonce': nonce,
                  'pwd': pwd,
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

