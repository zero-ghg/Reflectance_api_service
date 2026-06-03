# -*- coding: utf-8 -*-
'''
Created in 2016/03/28
@author: xjunior
'''
import sys
import time
import uuid
import webbrowser
import requests
# 看demo所在目录，添加路径
sys.path.append('../../..')
from demo.util import SignGenUtil

##有些输出是中文字符，统一设置一下编码
# reload(sys)
# sys.setdefaultencoding('utf8')

# 1. 调用方法的参数定义，并赋值
    # 1.1 接口url
    # 1.2 用户名&密码
    # 1.3 接口ID
    # 1.4 必选参数（按需加可选参数）
    #     资料：质控前标准格式单站多普勒雷达基数据
    #     时间段，前闭后开
    #     雷达站
    # 服务节点

# 服务节点
serviceNodeId = "NMIC_MUSIC_CMADAAS"
# 接口服务端IP和端口
serviceIp = "10.40.17.54:80"
# 用户名&密码
userId = 'NMIC_XTS_CMADAASTEST'
pwd = 'test1234'
# 序列化格式
dataFormat = 'text'
# 接口url
baseUrl = 'http://' + serviceIp + '/music-ws/api?\
serviceNodeId=' + serviceNodeId + '\
&userId=' + userId + '\
&interfaceId=getRadaFileByTimeRangeAndStaId\
&dataCode=RADA_L2_UFMT\
&timeRange=[20190601000000,20190601000600)\
&staIds=Z9859,Z9852,Z9856,Z9851,Z9855\
&dataFormat='
# 接口url一次拼接
baseUrl = baseUrl + dataFormat

# 接口url二次拼接函数
def conUrl():
    # 生成timestamp、nonce
    global baseUrl
    timestamp = str(int(round(time.time() * 1000)))
    nonce = str(uuid.uuid1())

    # 生成sign
    signParams = {'serviceNodeId': serviceNodeId,
                  'userId': userId,
                  'interfaceId': "getRadaFileByTimeRangeAndStaId",
                  'dataCode': "RADA_L2_UFMT",
                  'timeRange': "[20190601000000,20190601000600)",
                  'staIds': "Z9859,Z9852,Z9856,Z9851,Z9855",
                  'dataFormat': dataFormat,
                  'timestamp': timestamp,
                  'nonce': nonce,
                  'pwd': pwd
                  }
    signUtil = SignGenUtil.SignGenUtil()
    sign = signUtil.getSign(signParams)
    if (sign == ""):
        print("generate sign is None")
    # 拼接timestamp、nonce、sign
    baseUrl += '&timestamp=' + timestamp+'&nonce=' + nonce+'&sign=' + sign
    return baseUrl

def text_data():
    # 拼接接口url
    conUrl()
    # 请求url
    response=requests.get(baseUrl)
    # 获取url内容并解码
    text_data=response.content.decode('utf-8')
    # print(text_data.index('\n'))
    if 'returnCode="0"' in text_data:
        text_data=text_data[text_data.index('\n'):]
        # print(text_data[text_data.index('\n'):])
        # 保存text_data数据
        with open('outputdata_text.txt','w',encoding='utf-8') as file:
            file.write(text_data)
            file.close()

if __name__ == '__main__':
    # 处理json_data数据
    text_data()
    # 当前网页新标签打开
    webbrowser.open_new_tab(baseUrl)